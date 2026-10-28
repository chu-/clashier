import httpx
import pytest
from tests.support import read_yaml_document


def test_list_omits_subscription_urls(json_run):
    result, value = json_run("profile", "list")
    assert result.exit_code == 0
    assert [item["uid"] for item in value["data"]["items"]] == ["p1", "p2"]
    assert all("url" not in item for item in value["data"]["items"])
    assert value["data"]["source"] == "configured"
    assert "sub.example" not in result.stdout


@pytest.mark.parametrize("name", ["Backup 订阅", "p2"])
def test_activate_loads_and_verifies_without_rewriting_host_settings(json_run, config_dir, name, http):
    before = (config_dir / "verge.yaml").read_bytes()
    http.reply = lambda request: httpx.Response(204) if request.method == "PUT" else httpx.Response(
        200, json={"mode": "rule"} if request.url.path == "/configs"
        else {"proxies": {"DIRECT": {"type": "Direct"}}})
    result, value = json_run("profile", "activate", "--core-only", name)
    assert result.exit_code == 0
    assert value["data"]["status"] == "verified"
    assert value["data"]["reload"]["status"] == "accepted"
    assert read_yaml_document(config_dir / "profiles.yaml")["current"] == "p2"
    assert (config_dir / "verge.yaml").read_bytes() == before


def test_unknown_profile_is_a_structured_error(json_run):
    result, value = json_run("profile", "activate", "--core-only", "missing")
    assert result.exit_code == 1
    assert value["error"]["code"] == "NOT_FOUND"
    assert result.stderr


def test_delete_rejects_active_profile(json_run, config_dir):
    result, value = json_run("profile", "delete", "Main")
    assert result.exit_code == 1
    assert value["error"]["code"] == "PRECONDITION_FAILED"
    assert (config_dir / "profiles" / "p1.yaml").exists()
    result, value = json_run("profile", "delete", "Backup 订阅")
    assert result.exit_code == 0
    assert value["data"]["profile_uid"] == "p2"
    assert not (config_dir / "profiles" / "p2.yaml").exists()


def test_add_downloads_once_and_saves_unicode_content(json_run, config_dir, http):
    content = "proxies:\n  - {name: 节点}\n"
    http.reply = httpx.Response(200, text=content)
    result, value = json_run("profile", "add", "https://sub.example/token", "--name", "新订阅")
    assert result.exit_code == 0
    assert len(http.requests) == 1
    item = read_yaml_document(config_dir / "profiles.yaml")["items"][-1]
    assert item["name"] == "新订阅"
    assert (config_dir / "profiles" / item["file"]).read_text(encoding="utf-8") == content
    assert value["data"]["status"] == "saved"
    assert "https://sub.example/token" not in result.stdout + result.stderr


@pytest.mark.parametrize("response", [httpx.Response(403), httpx.ConnectError("unreachable")])
def test_download_errors_do_not_save_a_profile(json_run, config_dir, http, response):
    before = (config_dir / "profiles.yaml").read_bytes()
    http.reply = response
    result, value = json_run("profile", "add", "https://sub.example/private-token")
    assert result.exit_code == 1
    assert value["error"]["code"] == "DOWNLOAD_FAILED"
    assert (config_dir / "profiles.yaml").read_bytes() == before
    assert "private-token" not in result.stdout + result.stderr


def test_traffic_is_subscription_usage(json_run):
    result, value = json_run("profile", "traffic")
    assert result.exit_code == 0
    assert value["data"]["total_gb"] == 10.0
    assert value["data"]["source"] == "configured"
