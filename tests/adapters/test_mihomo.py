import json

import httpx
import pytest

from clashier.adapters.mihomo import Mihomo
from clashier.adapters.transport import normalize_controller
from clashier.errors import ControllerError


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "http://127.0.0.1:9097"),
        ("127.0.0.1:9097", "http://127.0.0.1:9097"),
        (":9090", "http://127.0.0.1:9090"),
        ("0.0.0.0:9090", "http://127.0.0.1:9090"),
        ("[::]:9090", "http://[::1]:9090"),
        ("http://192.0.2.10:9090/", "http://192.0.2.10:9090"),
        ("localhost", "http://localhost:9097"),
    ],
)
def test_controller_normalization_targets_the_expected_host(http, value, expected):
    http.reply = httpx.Response(200, json={"mode": "rule"})
    controller = Mihomo(value)
    assert controller.configs()["mode"] == "rule"
    assert http.requests[-1].url == httpx.URL(expected + "/configs")
    assert normalize_controller(controller.address) == controller.address


def test_bearer_header_and_timeout(http):
    http.reply = httpx.Response(200, json={"version": "1.18"})
    api = Mihomo("127.0.0.1:9097", "example-auth-token", timeout=2.5)
    assert api.version() == {"version": "1.18"}
    request = http.requests[0]
    assert request.headers["Authorization"] == "Bearer example-auth-token"
    assert request.extensions["timeout"]["read"] == 2.5
    assert str(request.url) == "http://127.0.0.1:9097/version"


def test_no_auth_header_without_secret(http):
    http.reply = httpx.Response(200, json={})
    Mihomo("127.0.0.1:9097", None).configs()
    assert "Authorization" not in http.requests[0].headers


def test_trust_env_disabled():
    assert Mihomo().session.trust_env is False


@pytest.mark.parametrize(
    "exc,needle",
    [
        (httpx.ConnectError("refused"), "Cannot connect"),
        (httpx.ReadTimeout("slow"), "timed out"),
    ],
)
def test_unreachable(http, exc, needle):
    http.reply = exc
    with pytest.raises(ControllerError, match=needle):
        Mihomo().configs()


def test_unauthorized(http):
    http.reply = httpx.Response(401, json={"message": "Unauthorized"})
    with pytest.raises(ControllerError) as info:
        Mihomo(secret="example-invalid-secret").configs()
    assert info.value.status == 401
    assert "secret" in str(info.value)


def test_error_message_propagates(http):
    http.reply = httpx.Response(400, json={"message": "Selector update error: proxy not exist"})
    with pytest.raises(ControllerError, match="proxy not exist"):
        Mihomo().select("G", "x")


@pytest.mark.parametrize("group,encoded_path", [
    ("a b/c#d?e", "/proxies/a%20b%2Fc%23d%3Fe"),
    ("🧪 示例", "/proxies/%F0%9F%A7%AA%20%E7%A4%BA%E4%BE%8B"),
])
def test_selection_preserves_group_as_one_path_segment(http, group, encoded_path):
    http.reply = httpx.Response(204)
    node = "🧪 Example Node / 示例"
    Mihomo().select(group, node)
    request = http.requests[0]
    assert request.method == "PUT"
    assert request.url.raw_path.decode("ascii") == encoded_path
    assert request.url.fragment == ""
    assert dict(request.url.params) == {}
    assert json.loads(request.content) == {"name": node}


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"delay": 123}, 123),
    (200, {"delay": 0}, 0),
    (504, {"message": "Timeout"}, None),
])
def test_measurement_uses_query_parameters_and_distinguishes_zero_from_timeout(http, status, payload, expected):
    http.reply = httpx.Response(status, json=payload)
    assert Mihomo().delay("candidate", "https://probe.invalid/health", 3000) == expected
    request = http.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/proxies/candidate/delay"
    assert dict(request.url.params) == {"url": "https://probe.invalid/health", "timeout": "3000"}


def test_delay_unknown_proxy_raises(http):
    http.reply = httpx.Response(404, json={"message": "resource not found"})
    with pytest.raises(ControllerError) as info:
        Mihomo().delay("missing")
    assert info.value.status == 404


def test_provider_nodes_are_projected_without_credentials_or_provider_urls(http):
    http.reply = httpx.Response(200, json={"providers": {"Example Provider": {
        "url": "https://sub.example/private-token", "proxies": [
            {"name": "Example Provider Node", "type": "Trojan", "password": "credential-sentinel",
             "server": "private.example", "history": [{"delay": 100}]}]}}})
    assert Mihomo().provider_proxies() == {
        "Example Provider Node": {"name": "Example Provider Node", "type": "Trojan"}}
    assert http.requests[0].method == "GET"
    assert http.requests[0].url.path == "/providers/proxies"


@pytest.mark.parametrize("provider", [
    "not an object", {"proxies": "not an array"}, {"proxies": [{"name": "Example Node"}]},
])
def test_invalid_provider_nodes_are_not_silently_omitted(http, provider):
    http.reply = httpx.Response(200, json={"providers": {"Example Provider": provider}})
    with pytest.raises(ControllerError) as info:
        Mihomo().provider_proxies()
    assert info.value.code == "INVALID_RESPONSE"


def test_pending_provider_has_no_loaded_nodes(http):
    http.reply = httpx.Response(200, json={"providers": {"Example Provider": {"proxies": None}}})
    assert Mihomo().provider_proxies() == {}
