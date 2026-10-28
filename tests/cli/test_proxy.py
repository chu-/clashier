from urllib.parse import unquote

import httpx
import pytest
from jsonschema import Draft202012Validator
from tests.conftest import CONTROLLER_SECRET, GROUP, NODE_A, NODE_B

from clashier.cli.protocol import load_schema

AUTO = "Example Auto"
NESTED = "Example Nested"
UNUSED = "Example Unused Node"
PROVIDED = "Example Provider Node"


def live_graph():
    return {"proxies": {
        GROUP: {"type": "Selector", "now": NODE_A, "all": [NODE_A, NODE_B, "DIRECT"]},
        NODE_A: {"type": "VLESS", "password": "do-not-publish"},
        NODE_B: {"type": "VLESS"}, "DIRECT": {"type": "Direct"}}}


@pytest.fixture
def exploration_runtime(http):
    graph = live_graph()
    graph["proxies"].update({
        AUTO: {"type": "URLTest", "now": NODE_A, "all": [NODE_A, NODE_B, PROVIDED, NODE_A]},
        NESTED: {"type": "Selector", "now": AUTO, "all": [AUTO]},
        UNUSED: {"type": "Socks5", "server": "private.example", "password": "credential-sentinel"},
    })
    def reply(request):
        if request.url.path == "/providers/proxies":
            return httpx.Response(200, json={"providers": {"Example Provider": {
                "vehicleType": "HTTP", "url": "https://sub.example/provider-secret",
                "proxies": [{"name": PROVIDED, "type": "Trojan", "password": "provider-credential-sentinel"},
                            {"name": NODE_A, "type": "Socks5"}]}}})
        return httpx.Response(200, json={"mode": "rule"} if request.url.path == "/configs" else graph)

    http.reply = reply


def test_default_list_shows_all_live_nodes_with_direct_group_membership(
    json_run, config_dir, exploration_runtime, http
):
    before = {path: path.read_bytes() for path in config_dir.glob("*.yaml")}
    result, value = json_run("proxy", "list")
    assert result.exit_code == 0, result.output
    data = value["data"]
    Draft202012Validator(load_schema("proxy-list-result")).validate(data)
    assert data["group"] is None and data["selected"] is None
    assert data["mode"] == "rule"
    nodes = {item["name"]: item for item in data["items"]}
    assert set(nodes) == {NODE_A, NODE_B, "DIRECT", UNUSED, PROVIDED}
    assert nodes[NODE_A]["groups"] == [GROUP, AUTO]
    assert nodes[NODE_A]["type"] == "VLESS"
    assert nodes[NODE_A]["selected_in"] == [GROUP, AUTO]
    assert nodes[NODE_B]["groups"] == [GROUP, AUTO]
    assert nodes[NODE_B]["selected_in"] == []
    assert nodes[UNUSED]["groups"] == []
    assert nodes[UNUSED]["selected_in"] == []
    assert nodes[PROVIDED]["groups"] == [AUTO]
    assert nodes[PROVIDED]["type"] == "Trojan"
    assert all(secret not in result.stdout for secret in ["do-not-publish", "credential-sentinel", "private.example"])
    assert "provider-secret" not in result.stdout
    assert all(request.method == "GET" for request in http.requests)
    assert {request.url.path for request in http.requests} == {"/configs", "/proxies", "/providers/proxies"}
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_default_human_list_explains_group_selection_and_offers_group_exploration(run, exploration_runtime):
    result = run("proxy", "list")
    assert result.exit_code == 0, result.output
    assert "Member of" in result.stdout and "Selected by" in result.stdout
    assert NODE_A in result.stdout and UNUSED in result.stdout
    assert "proxy groups" in result.stdout
    assert "does not support manual selection" not in result.stdout
    assert "None" not in result.stdout


def test_group_list_keeps_nested_candidates_and_each_groups_selection(json_run, exploration_runtime):
    result, value = json_run("proxy", "list", "--group", NESTED)
    assert result.exit_code == 0, result.output
    assert value["data"]["selected"] == AUTO
    assert value["data"]["items"] == [{"name": AUTO, "type": "URLTest"}]
    _, value = json_run("proxy", "groups")
    groups = {item["name"]: item for item in value["data"]["items"]}
    assert groups[GROUP]["selected"] == NODE_A
    assert groups[AUTO]["selected"] == NODE_A and groups[AUTO]["writable"] is False
    assert groups[NESTED]["selected"] == AUTO


def test_default_list_handles_an_empty_runtime_graph(json_run, http):
    def reply(request):
        data = {"/configs": {"mode": "direct"}, "/providers/proxies": {"providers": {}}}
        return httpx.Response(200, json=data.get(request.url.path, {"proxies": {}}))

    http.reply = reply
    result, value = json_run("proxy", "list")
    assert result.exit_code == 0, result.output
    assert value["data"]["items"] == []
    assert value["data"]["mode"] == "direct"


def test_live_status_and_choices(json_run, http):
    http.reply = lambda request: httpx.Response(
        200, json={"mode": "rule"} if request.url.path == "/configs" else live_graph())
    result, value = json_run("status")
    assert result.exit_code == 0
    assert value["data"]["mode"] == "rule"
    assert value["context"]["profile_uid"] == "p1"
    result, value = json_run("proxy", "list", "--group", GROUP)
    assert result.exit_code == 0
    assert [item["name"] for item in value["data"]["items"]] == [NODE_A, NODE_B, "DIRECT"]
    assert "do-not-publish" not in result.stdout
    assert json_run("proxy", "list", "--group", "missing")[1]["error"]["code"] == "NOT_FOUND"


def test_probe_is_one_named_measurement(json_run, http):
    def reply(request):
        if request.url.path.endswith("/delay"):
            if NODE_A in unquote(request.url.path):
                return httpx.Response(200, json={"delay": 88})
            return httpx.Response(504)
        return httpx.Response(200, json=live_graph()["proxies"][GROUP])

    http.reply = reply
    result, value = json_run("proxy", "probe", "--group", GROUP, "--name", NODE_A)
    assert result.exit_code == 0
    assert value["data"]["latency_ms"] == 88
    assert all(request.headers["Authorization"] == "Bearer " + CONTROLLER_SECRET for request in http.requests)
    assert sum(request.url.path.endswith("/delay") for request in http.requests) == 1
    assert json_run("proxy", "probe", "--group", GROUP, "--name", NODE_B)[1]["data"]["status"] == "timeout"


def test_connection_failure_is_not_file_based_success(json_run, http, tmp_path):
    http.reply = httpx.ConnectError("refused")
    missing = tmp_path / "missing"
    result, value = json_run("--config-dir", str(missing), "status")
    assert result.exit_code == 1
    assert value["error"]["code"] == "CONTROLLER_UNAVAILABLE"
    assert not missing.exists()


def test_controller_rejections_are_json_errors(json_run, http):
    for status, code in ((400, "CONTROLLER_REJECTED"), (404, "NOT_FOUND"), (401, "AUTH_FAILED")):
        http.reply = httpx.Response(status, json={"message": "rejected"})
        result, value = json_run("proxy", "select", "--group", GROUP, "--name", NODE_B)
        assert result.exit_code == 1
        assert value["error"]["code"] == code
