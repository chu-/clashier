import pytest
import yaml
from tests.conftest import NODE_B


def test_backup_and_restore_roundtrip(json_run, config_dir):
    result, value = json_run("backup", "create", "snap 1")
    assert result.exit_code == 0
    assert value["data"]["status"] == "saved"
    assert json_run("backup", "list")[1]["data"]["items"][0]["name"] == "snap 1"
    copied = config_dir / "clash-verge-rev-backup" / "snap 1" / "clash-verge.yaml"
    assert NODE_B in copied.read_text(encoding="utf-8")
    json_run("host", "tun", "set", "on")
    result, value = json_run("backup", "restore", "snap 1")
    assert result.exit_code == 0
    assert value["data"]["status"] == "pending"
    configured = yaml.safe_load((config_dir / "verge.yaml").read_text(encoding="utf-8"))
    assert configured["enable_tun_mode"] is False


@pytest.mark.parametrize("name", ["../escape", "..", "a/b"])
def test_backup_rejects_path_traversal(json_run, name):
    assert json_run("backup", "create", name)[0].exit_code == 2
    result, value = json_run("backup", "restore", name)
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"


def test_missing_backup_is_structured(json_run):
    result, value = json_run("backup", "restore", "missing")
    assert result.exit_code == 1
    assert value["error"]["code"] == "NOT_FOUND"
