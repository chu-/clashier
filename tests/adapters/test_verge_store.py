import os
import sys

import pytest

from clashier.adapters.verge_store import VergeStore
from clashier.adapters.yaml_files import read_mapping


def test_writes_preserve_order_and_unicode(config_dir):
    path = config_dir / "verge.yaml"
    path.write_text("zeta: 节点\nalpha: 2\n", encoding="utf-8")
    VergeStore(config_dir).update_settings({"enable_tun_mode": True})
    assert list(read_mapping(path)) == ["zeta", "alpha", "enable_tun_mode"]
    assert read_mapping(path)["zeta"] == "节点"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file permissions")
def test_writes_preserve_file_mode(config_dir):
    path = config_dir / "verge.yaml"
    os.chmod(str(path), 0o640)
    VergeStore(config_dir).update_settings({"enable_tun_mode": True})
    assert path.stat().st_mode & 0o777 == 0o640
