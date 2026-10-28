import yaml


def test_config_queries_share_json_protocol(json_run, config_dir):
    result, value = json_run("config", "path")
    assert result.exit_code == 0
    assert value["data"]["path"] == str(config_dir)
    assert value["data"]["exists"] is True
    assert json_run("config", "dns")[1]["data"]["dns"]["nameserver"] == ["192.0.2.53"]
    rules = json_run("config", "rules", "--type", "GEOIP")[1]["data"]["items"]
    assert rules == [{"type": "GEOIP", "value": "CN", "payload": "DIRECT"}]
    assert json_run("config", "get", "core")[1]["data"]["config"]["mixed-port"] == 7897
    assert json_run("core")[1]["data"]["core"] == "verge-mihomo"


def test_set_and_refresh_are_pending(json_run, config_dir):
    for key, value in (("foo", "true"), ("number", "12"), ("label", "hello")):
        result, result_data = json_run("config", "set", key, value)
        assert result.exit_code == 0
        assert result_data["data"]["status"] == "pending"
    configured = yaml.safe_load((config_dir / "verge.yaml").read_text(encoding="utf-8"))
    assert configured["foo"] is True
    assert configured["number"] == 12
    assert configured["label"] == "hello"
    assert json_run("config", "refresh")[1]["data"]["status"] == "pending"


def test_missing_configuration_is_not_created_by_queries(json_run, tmp_path):
    missing = tmp_path / "missing"
    result, value = json_run("--config-dir", str(missing), "config", "path")
    assert result.exit_code == 0
    assert value["data"]["exists"] is False
    assert not missing.exists()
    assert json_run("--config-dir", str(missing), "config", "refresh")[0].exit_code == 1
