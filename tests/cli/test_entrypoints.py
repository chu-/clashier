import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from clashier import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_help_and_version(run):
    result = run("--help")
    assert result.exit_code == 0
    assert "profile" in result.stdout
    assert "host" in result.stdout
    assert "backup" in result.stdout
    assert __version__ in run("--version").stdout


def test_single_source_launcher_works_outside_repository(config_dir, tmp_path):
    env = dict(os.environ, CLASH_VERGE_DIR=str(config_dir), PYTHONIOENCODING="ascii")
    result = subprocess.run([sys.executable, str(ROOT / "clashier.py"), "--output", "json", "profile", "list"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["items"][1]["name"] == "Backup 订阅"


def test_unknown_resource_returns_a_structured_error(json_run):
    result, value = json_run("unknown-resource")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("args", [("profile", "list", "--json"), ("logs", "read", "--json"),
                                  ("proxy", "groups", "--json")])
def test_output_has_one_global_option(json_run, args):
    assert json_run(*args)[0].exit_code == 2
