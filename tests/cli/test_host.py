import pytest
import yaml

from clashier.errors import OperationError


@pytest.mark.parametrize("resource,field", [("proxy", "enable_system_proxy"), ("tun", "enable_tun_mode")])
def test_explicit_host_switch_is_idempotent(json_run, config_dir, resource, field):
    for _ in range(2):
        result, value = json_run("host", resource, "set", "on")
        assert result.exit_code == 0
        assert value["data"]["status"] == "pending"
        assert value["data"]["enabled"] is True
    configured = yaml.safe_load((config_dir / "verge.yaml").read_text(encoding="utf-8"))
    assert configured[field] is True
    result, value = json_run("host", resource, "set", "off")
    assert result.exit_code == 0
    assert value["data"]["enabled"] is False
    assert json_run("host", resource, "set", "toggle")[0].exit_code == 2


def test_host_queries_are_marked_configured(json_run):
    for resource in ("proxy", "tun", "ports"):
        result, value = json_run("host", resource, "get")
        assert result.exit_code == 0
        assert value["data"]["source"] == "configured"


def test_ports_set_and_validation(json_run, config_dir):
    result, value = json_run("host", "ports", "set", "socks", "1080", "--enable")
    assert result.exit_code == 0
    assert value["data"]["ports"]["socks_port"] == 1080
    configured = yaml.safe_load((config_dir / "verge.yaml").read_text(encoding="utf-8"))
    assert configured["verge_socks_port"] == 1080
    assert configured["verge_socks_enabled"] is True
    assert json_run("host", "ports", "set", "http", "70000")[0].exit_code == 2


def test_restart_reports_the_host_operation_result(json_run, monkeypatch):
    events = []

    def missing_app(timeout):
        raise OperationError("NOT_FOUND", "Clash Verge app not found")

    monkeypatch.setattr("clashier.platforms.restart_verge", missing_app)
    result, value = json_run("host", "restart")
    assert result.exit_code == 1
    assert value["error"]["code"] == "NOT_FOUND"
    assert events == []
    monkeypatch.setattr("clashier.platforms.restart_verge", lambda timeout: events.append("restart"))
    result, value = json_run("host", "restart")
    assert result.exit_code == 0
    assert events == ["restart"]
    assert value["data"]["status"] == "started"


def test_open_and_webui(json_run, config_dir, monkeypatch):
    opened = []
    monkeypatch.setattr("clashier.platforms.open_directory", opened.append)
    result, value = json_run("host", "open", "logs")
    assert result.exit_code == 0
    assert opened == [config_dir / "logs"]
    assert value["data"]["path"] == str(config_dir / "logs")
    result, value = json_run("host", "webui")
    assert result.exit_code == 0
    assert value["data"]["items"][0]["name"] == "yacd"
