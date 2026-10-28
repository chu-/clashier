import os
from pathlib import Path

import pytest
import yaml
from tests.conftest import GROUP, NODE_B
from tests.support import write_yaml_document

from clashier.adapters.verge_store import VergeStore
from clashier.adapters.yaml_files import write_mapping
from clashier.errors import OperationError


@pytest.mark.parametrize("contents", ["- unexpected\n", "items: invalid\n", "items:\n  - missing_uid: true\n"])
def test_invalid_profile_catalog_fails_before_a_write(config_dir, contents):
    catalog = config_dir / "profiles.yaml"
    catalog.write_text(contents, encoding="utf-8")
    with pytest.raises(OperationError, match="profiles.yaml"):
        VergeStore(config_dir).profiles.activate("p2")
    assert catalog.read_text(encoding="utf-8") == contents


def test_same_named_profiles_require_an_exact_uid(config_dir):
    catalog = config_dir / "profiles.yaml"
    values = yaml.safe_load(catalog.read_text(encoding="utf-8"))
    values["items"][1]["name"] = "Main"
    write_yaml_document(catalog, values)
    profiles = VergeStore(config_dir).profiles
    with pytest.raises(OperationError) as error:
        profiles.find("Main")
    assert error.value.code == "AMBIGUOUS_TARGET"
    assert profiles.find("p2")["uid"] == "p2"


def test_profile_selection_checks_the_current_uid_before_writing(config_dir):
    catalog = config_dir / "profiles.yaml"
    before = catalog.read_bytes()
    with pytest.raises(OperationError) as error:
        VergeStore(config_dir).profiles.set_selection("p2", GROUP, NODE_B)
    assert error.value.code == "STALE_CONTEXT"
    assert catalog.read_bytes() == before


def test_active_profile_cannot_be_deleted_through_the_store(config_dir):
    with pytest.raises(OperationError) as error:
        VergeStore(config_dir).profiles.delete("p1")
    assert error.value.code == "PRECONDITION_FAILED"
    assert (config_dir / "profiles/p1.yaml").exists()


def test_subscription_imports_have_unique_ids(config_dir):
    profiles = VergeStore(config_dir).profiles
    first = profiles.import_subscription("https://sub.invalid/one", "proxies: []\n", "One")
    second = profiles.import_subscription("https://sub.invalid/two", "proxies: []\n", "Two")
    assert first["uid"] != second["uid"]
    assert profiles.find(first["uid"])["name"] == "One"
    assert profiles.find(second["uid"])["name"] == "Two"


def test_backup_name_collision_preserves_existing_snapshot(config_dir):
    store = VergeStore(config_dir)
    snapshot = Path(store.create_backup("before"))
    original = (snapshot / "verge.yaml").read_bytes()
    store.update_settings({"enable_tun_mode": True})
    with pytest.raises(OperationError) as error:
        store.create_backup("before")
    assert error.value.code == "ALREADY_EXISTS"
    assert (snapshot / "verge.yaml").read_bytes() == original


def test_invalid_settings_document_is_not_replaced(config_dir):
    path = config_dir / "verge.yaml"
    path.write_text("- invalid settings\n", encoding="utf-8")
    with pytest.raises(OperationError, match="verge.yaml"):
        VergeStore(config_dir).update_settings({"enable_tun_mode": True})
    assert path.read_text(encoding="utf-8") == "- invalid settings\n"


def test_atomic_replacement_failure_preserves_the_original_file_and_cleans_temp(config_dir, monkeypatch):
    target = config_dir / "verge.yaml"
    original = target.read_bytes()

    def denied(*args):
        raise PermissionError("replacement denied")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        write_mapping(target, {"new": "value"})
    assert target.read_bytes() == original
    assert list(config_dir.glob(".clashier-*")) == []


def test_unchanged_settings_do_not_trigger_a_file_rewrite(config_dir):
    target = config_dir / "verge.yaml"
    os.utime(str(target), (1, 1))
    before = target.stat().st_mtime_ns
    VergeStore(config_dir).update_settings({"enable_system_proxy": False})
    assert target.stat().st_mtime_ns == before
