import json

from tests.conftest import make_runner

from clashier.cli.main import clashier


def test_health_uses_explicit_proxy_without_reaching_the_target_host(local_core, config_dir):
    server = local_core()
    result = make_runner().invoke(clashier, ["--output", "json", "health", "--url", "http://health.invalid/version",
                                       "--proxy", server.address])
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert value["data"]["status"] == "reachable"
    assert value["data"]["http_status"] == 200
    assert value["data"]["via_proxy"] is True


def test_health_direct_and_non_success_status(local_core):
    server = local_core()
    for path, expected in (("/version", 0), ("/missing", 1)):
        result = make_runner().invoke(clashier, ["--output", "json", "health", "--url", server.address + path])
        assert result.exit_code == expected
        value = json.loads(result.stdout)
        assert value["data"]["via_proxy"] is False
        if expected:
            assert value["error"]["code"] == "HEALTH_CHECK_FAILED"
            assert value["data"]["http_status"] == 404
