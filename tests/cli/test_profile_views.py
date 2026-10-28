import re
import shlex
import sys

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator
from tests.conftest import GROUP, NODE_A, NODE_B
from tests.support import read_yaml_document, write_yaml_document

from clashier.cli.protocol import load_schema


@pytest.fixture
def declared_profiles(config_dir):
    document = {
        "proxies": [{"name": name, "type": "vless", "password": "example-password-not-real",
                     "server": "node.invalid"} for name in (NODE_A, NODE_B)],
        "proxy-groups": [{"name": GROUP, "type": "select", "proxies": [NODE_A, NODE_B, "DIRECT"]}],
    }
    for uid in ("p1", "p2"):
        write_yaml_document(config_dir / "profiles" / (uid + ".yaml"), document)
    return document


def graph_response(request):
    if request.method == "PUT" and request.url.path == "/configs":
        return httpx.Response(204)
    if request.url.path == "/configs":
        return httpx.Response(200, json={"mode": "rule"})
    return httpx.Response(200, json={"proxies": {
        GROUP: {"type": "Selector", "now": NODE_A, "all": [NODE_A, NODE_B, "DIRECT"]},
        NODE_A: {"type": "VLESS"}, NODE_B: {"type": "VLESS"}, "DIRECT": {"type": "Direct"}}})


@pytest.fixture
def acknowledged_stale_runtime(http, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("clashier.models.time.monotonic", lambda: clock[0])

    def reply(request):
        if request.method == "PUT":
            return httpx.Response(204)
        if request.url.path == "/configs":
            return httpx.Response(200, json={"mode": "rule"})
        clock[0] += 1.0
        return httpx.Response(200, json={"proxies": {}})

    http.reply = reply


def test_activation_hotloads_profile_instead_of_only_changing_catalog(json_run, declared_profiles, http):
    import json

    loaded = []

    def reply(request):
        if request.method == "PUT" and request.url.path == "/configs":
            loaded.append(yaml.safe_load(json.loads(request.content)["payload"]))
            return httpx.Response(204)
        return graph_response(request)

    http.reply = reply
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 0, result.output
    assert len(loaded) == 1
    assert [node["name"] for node in loaded[0]["proxies"]] == [NODE_A, NODE_B]
    assert value["data"]["status"] == "verified"


@pytest.mark.parametrize("response, code, status", [
    (httpx.Response(400, json={"message": "example-password-not-real"}), "CONTROLLER_REJECTED", "not_applied"),
    (httpx.ConnectError("offline"), "CONTROLLER_UNAVAILABLE", "not_applied"),
    (httpx.ReadTimeout("lost response"), "OUTCOME_UNKNOWN", "unknown"),
    (httpx.Response(200, json={"mode": "rule"}), "OUTCOME_UNKNOWN", "unknown"),
])
def test_reload_rejection_or_uncertainty_does_not_write_files(
    json_run, config_dir, declared_profiles, http, response, code, status
):
    before = {name: (config_dir / name).read_bytes() for name in ("profiles.yaml", "clash-verge.yaml", "verge.yaml")}
    http.reply = response
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == code
    assert value["data"]["status"] == status
    assert len(http.requests) == 1 and http.requests[0].method == "PUT"
    assert http.requests[0].url.params["force"] == "true"
    assert all((config_dir / name).read_bytes() == content for name, content in before.items())
    assert "example-password-not-real" not in result.stdout + result.stderr


def test_reload_accepted_but_disk_failure_reports_known_runtime_effect(
    json_run, config_dir, declared_profiles, http, monkeypatch
):
    before = (config_dir / "profiles.yaml").read_bytes()
    http.reply = graph_response

    def cannot_save(*args):
        raise OSError("example disk failure")

    monkeypatch.setattr("clashier.application.profiles.write_mapping", cannot_save)
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "PERSISTENCE_FAILED"
    assert value["data"]["status"] == "partial"
    assert value["data"]["reload"]["status"] == "accepted"
    assert value["data"]["configuration"]["status"] == "failed"
    assert (config_dir / "profiles.yaml").read_bytes() == before


def test_inspect_inactive_profile_is_offline_and_sanitized(json_run, config_dir, declared_profiles, http):
    before = (config_dir / "profiles.yaml").read_bytes()
    result, value = json_run("profile", "show", "p2")
    assert result.exit_code == 0
    assert value["data"]["is_current"] is False
    assert value["data"]["groups"][0]["proxies"] == [NODE_A, NODE_B, "DIRECT"]
    assert value["data"]["items"] == [{"name": node, "type": "vless"} for node in (NODE_A, NODE_B)]
    assert value["data"]["source"] == "configured"
    assert value["context"] is None
    assert "example-password-not-real" not in result.stdout
    assert "node.invalid" not in result.stdout
    assert not http.requests
    assert (config_dir / "profiles.yaml").read_bytes() == before


@pytest.mark.parametrize("group", [None, GROUP])
def test_list_profile_nodes_without_activating(json_run, declared_profiles, group):
    args = ("--group", group) if group else ()
    result, value = json_run("proxy", "list", "--profile", "Backup 订阅", *args)
    assert result.exit_code == 0
    data = value["data"]
    Draft202012Validator(load_schema("proxy-list-result")).validate(data)
    assert data["profile_uid"] == "p2"
    assert data["selected"] is None
    assert data["writable"] is False
    assert [node["name"] for node in data["items"]] == [NODE_A, NODE_B] + (["DIRECT"] if group else [])


def test_offline_groups_do_not_claim_runtime_selection(json_run, declared_profiles):
    result, value = json_run("proxy", "groups", "--profile", "p2")
    assert result.exit_code == 0
    assert value["data"]["items"][0]["name"] == GROUP
    assert "selected" not in value["data"]["items"][0]


def test_dynamic_providers_are_named_without_downloading_or_exposing_urls(
    json_run, config_dir, declared_profiles, http
):
    declared_profiles["proxy-providers"] = {"Example Provider": {"type": "http", "url": "https://sub.example/token"}}
    declared_profiles["proxy-groups"][0]["use"] = ["Example Provider"]
    write_yaml_document(config_dir / "profiles/p1.yaml", declared_profiles)
    result, value = json_run("profile", "show", "p1")
    assert result.exit_code == 0
    assert value["data"]["complete"] is False
    assert value["data"]["providers"] == [{"name": "Example Provider"}]
    assert "sub.example" not in result.stdout
    assert not http.requests
    http.reply = lambda request: httpx.Response(200, json={"providers": {"Example Provider": {}}}) if (
        request.url.path == "/providers/proxies") else graph_response(request)
    result, value = json_run("profile", "verify", "p1")
    assert result.exit_code == 0
    assert value["data"]["verification"]["status"] == "matched"
    assert all(request.url.host == "127.0.0.1" for request in http.requests)


@pytest.mark.parametrize("document", [
    {"proxies": "not a list"},
    {"proxies": [{"name": NODE_A}]},
    {"proxy-groups": [{"name": GROUP, "type": "select", "proxies": [42]}]},
    {"proxy-providers": ["wrong"]},
])
def test_invalid_profile_graph_fails_before_activation(json_run, config_dir, document):
    before = (config_dir / "profiles.yaml").read_bytes()
    write_yaml_document(config_dir / "profiles/p2.yaml", document)
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "CONFIGURATION_ERROR"
    assert (config_dir / "profiles.yaml").read_bytes() == before


def test_missing_content_and_unknown_group_are_explicit(json_run, config_dir, declared_profiles):
    assert json_run("proxy", "list", "--profile", "p2", "--group", "missing")[1]["error"]["code"] == "NOT_FOUND"
    (config_dir / "profiles/p2.yaml").unlink()
    assert json_run("profile", "show", "p2")[1]["error"]["code"] == "NOT_FOUND"


def test_verified_graph_has_an_explicit_scope(json_run, declared_profiles, http):
    http.reply = graph_response
    result, value = json_run("profile", "verify", "p1")
    assert result.exit_code == 0
    assert value["data"]["status"] == "verified"
    assert value["data"]["verification"] == {
        "scope": "rendered_proxy_graph", "profile_identity": "not_exposed", "status": "matched"}
    assert value["context"]["profile_uid"] == "p1"
    assert all(request.method == "GET" for request in http.requests)


def test_inactive_profile_cannot_be_verified_even_with_identical_nodes(json_run, declared_profiles, http):
    http.reply = graph_response
    result, value = json_run("profile", "verify", "p2")
    assert result.exit_code == 1
    assert value["data"]["verification"]["reason"] == "profile_not_current"
    assert not http.requests


def test_verification_waits_for_gui_catalog_persistence(json_run, config_dir, declared_profiles, http, monkeypatch):
    sleeps = []

    def persist_gui_selection(seconds):
        sleeps.append(seconds)
        catalog = read_yaml_document(config_dir / "profiles.yaml")
        catalog["current"] = "p2"
        write_yaml_document(config_dir / "profiles.yaml", catalog)
        core = read_yaml_document(config_dir / "clash-verge.yaml")
        core["external-controller"] = "192.0.2.10:9090"
        write_yaml_document(config_dir / "clash-verge.yaml", core)

    def reply(request):
        assert request.url.host == "192.0.2.10"
        return graph_response(request)

    monkeypatch.setattr("clashier.application.profiles.time.sleep", persist_gui_selection)
    http.reply = reply
    result, value = json_run("profile", "verify", "p2", "--wait")
    assert result.exit_code == 0
    assert len(sleeps) == 1
    assert value["data"]["status"] == "verified"
    assert value["context"]["profile_uid"] == "p2"


def test_activation_observes_delayed_graph_without_retrying_writes(json_run, config_dir, declared_profiles, http):
    observations = []

    def reply(request):
        if request.url.path == "/proxies":
            observations.append(True)
            if len(observations) == 1:
                return httpx.Response(200, json={"proxies": {"DIRECT": {"type": "Direct"}}})
        return graph_response(request)

    http.reply = reply
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 0
    assert len(observations) == 2
    assert value["context"]["profile_uid"] == "p2"
    assert read_yaml_document(config_dir / "profiles.yaml")["current"] == "p2"
    assert sum(request.method == "PUT" for request in http.requests) == 1


def test_reload_acknowledged_but_unverified_reports_partial_effect(
    json_run, config_dir, declared_profiles, acknowledged_stale_runtime
):
    result, value = json_run("--timeout", "0.1", "profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "PROFILE_UNCONFIRMED"
    assert value["data"]["status"] == "partial"
    assert value["data"]["reload"]["status"] == "accepted"
    assert read_yaml_document(config_dir / "profiles.yaml")["current"] == "p2"


@pytest.mark.parametrize("response, code", [
    (httpx.ConnectError("offline"), "PROFILE_UNCONFIRMED"),
    (httpx.Response(401), "AUTH_FAILED"),
])
def test_verification_reports_unknown_or_auth_failure(json_run, declared_profiles, http, response, code):
    http.reply = response
    result, value = json_run("profile", "verify", "p1")
    assert result.exit_code == 1
    assert value["error"]["code"] == code
    assert value["data"]["status"] == "unconfirmed"


def test_verification_rejects_standalone_controller(json_run, declared_profiles, http):
    result, value = json_run("--controller", "http://192.0.2.10:9090", "profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert not http.requests


def test_removed_restart_option_is_rejected(json_run, config_dir, declared_profiles):
    before = (config_dir / "profiles.yaml").read_bytes()
    result, value = json_run("profile", "activate", "--core-only", "p2", "--restart")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"
    assert (config_dir / "profiles.yaml").read_bytes() == before


def test_verification_detects_profile_change_during_read(json_run, config_dir, declared_profiles, http):
    def reply(request):
        if request.url.path == "/proxies":
            catalog = read_yaml_document(config_dir / "profiles.yaml")
            catalog["current"] = "p2"
            write_yaml_document(config_dir / "profiles.yaml", catalog)
        return graph_response(request)

    http.reply = reply
    result, value = json_run("profile", "verify", "p1")
    assert result.exit_code == 1
    assert value["error"]["code"] == "STALE_CONTEXT"


def _hint_args(output, resource):
    lines = [line.strip() for line in output.splitlines() if line.strip().startswith("clashier ")]
    for line in lines:
        if sys.platform == "win32":
            args = [match.group(1).replace("''", "'") if match.group(1) is not None else match.group(2)
                    for match in re.finditer(r"'((?:[^']|'')*)'|(\S+)", line)]
        else:
            args = shlex.split(line)
        if resource in args:
            return args[1:]
    raise AssertionError("Expected an actionable command hint")


def test_human_profile_list_distinguishes_configured_state_and_offers_a_working_next_step(
    run, config_dir, declared_profiles, http
):
    result = run("profile", "list")
    assert result.exit_code == 0
    assert not result.stdout.startswith("{")
    assert "Current (configured)" in result.stdout
    assert "Inactive" in result.stdout
    args = _hint_args(result.stdout, "show")
    assert args[args.index("--config-dir") + 1] == str(config_dir)
    details = run(*args)
    assert details.exit_code == 0
    assert "Backup 订阅" in details.stdout
    assert GROUP in details.stdout and NODE_A in details.stdout
    assert "example-password-not-real" not in details.stdout
    assert "node.invalid" not in details.stdout
    assert not http.requests


def test_duplicate_profile_names_remain_distinguishable_and_hints_use_uids(
    run, config_dir, declared_profiles
):
    catalog = read_yaml_document(config_dir / "profiles.yaml")
    for item in catalog["items"]:
        item["name"] = "Example Subscription"
    write_yaml_document(config_dir / "profiles.yaml", catalog)
    result = run("profile", "list")
    assert "Example Subscription (p1)" in result.stdout
    assert "Example Subscription (p2)" in result.stdout
    args = _hint_args(result.stdout, "show")
    assert args[-1] == "p2"
    assert run(*args).exit_code == 0


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_human_offline_exploration_preserves_special_names_in_copyable_commands(
    run, config_dir, declared_profiles, http, monkeypatch, platform
):
    monkeypatch.setattr("clashier.cli.render.sys.platform", platform)
    group = "Example 'Group' $value #1"
    declared_profiles["proxy-groups"][0]["name"] = group
    declared_profiles["proxy-providers"] = {"Example Provider": {"url": "https://sub.example/private-token"}}
    declared_profiles["proxy-groups"][0]["use"] = ["Example Provider"]
    write_yaml_document(config_dir / "profiles/p2.yaml", declared_profiles)
    preview = run("profile", "show", "p2")
    args = _hint_args(preview.stdout, "--group")
    assert args[args.index("--group") + 1] == group
    choices = run(*args)
    assert choices.exit_code == 0
    assert "not observed (offline)" in choices.stdout
    assert "Example Provider" in choices.stdout
    assert "Direct (no proxy)" in choices.stdout
    assert "private-token" not in preview.stdout + choices.stdout
    assert not http.requests


def test_human_live_choices_show_the_current_node_and_keep_json_clean(run, json_run, http):
    http.reply = graph_response
    human = run("proxy", "list", "--group", GROUP)
    assert human.exit_code == 0
    assert "Source: running controller" in human.stdout
    assert "Current" in next(line for line in human.stdout.splitlines() if NODE_A in line and "VLESS" in line)
    assert NODE_B in _hint_args(human.stdout, "select")
    result, value = json_run("proxy", "list", "--group", GROUP)
    assert result.exit_code == 0
    assert value["data"]["selected"] == NODE_A
    assert "Source: running controller" not in result.stdout


def test_human_reload_and_failed_verification_explain_partial_state(
    run, config_dir, declared_profiles, acknowledged_stale_runtime
):
    pending = run("--timeout", "0.1", "profile", "activate", "--core-only", "p2")
    assert pending.exit_code == 1
    assert "Partially applied" in pending.stderr
    assert read_yaml_document(config_dir / "profiles.yaml")["current"] == "p2"
    failed = run("profile", "verify", "p2")
    assert failed.exit_code == 1
    assert failed.stdout == ""
    assert "Waiting for core confirmation" in failed.stderr
    assert "running graph does not match" in failed.stderr
    assert _hint_args(failed.stderr, "verify")[-4:] == ["profile", "verify", "p2", "--wait"]


def test_followup_hints_keep_target_options_but_omit_secrets(run, declared_profiles):
    result = run("--controller", "http://192.0.2.10:9090", "--instance", "example-instance", "--secret",
                 "example-auth-token-not-real", "profile", "show", "p2")
    assert result.exit_code == 0
    args = _hint_args(result.stdout, "--group")
    assert args[args.index("--controller") + 1] == "http://192.0.2.10:9090"
    assert args[args.index("--instance") + 1] == "example-instance"
    assert "--secret" not in args
    assert "example-auth-token-not-real" not in result.stdout


@pytest.mark.parametrize("scheme", ["http://", ""])
def test_authenticated_controller_is_not_disclosed_in_hints(run, declared_profiles, scheme):
    result = run("--controller", scheme + "example-user:example-password-not-real@192.0.2.10:9090",
                 "profile", "show", "p2")
    assert result.exit_code == 0
    assert "example-password-not-real" not in result.stdout
    assert "example-user" not in result.stdout
    assert "Retain your authenticated --controller option" in result.stdout
