from pathlib import Path

import pytest

from clashier import platforms
from clashier.errors import OperationError


def test_platform_names():
    assert platforms.platform_name("darwin") == "macos"
    assert platforms.platform_name("win32") == "windows"
    assert platforms.platform_name("cygwin") == "windows"
    assert platforms.platform_name("linux") == "linux"


def test_unsupported_platform_is_not_assumed_to_be_linux():
    with pytest.raises(OperationError) as error:
        platforms.platform_name("freebsd")
    assert error.value.code == "UNSUPPORTED_OPERATION"


def test_macos_candidates(tmp_path):
    c = platforms.config_locations("darwin", {}, tmp_path)
    assert c[0] == tmp_path / "Library" / "Application Support" / platforms.VERGE_APP_ID


def test_windows_candidates_use_appdata(tmp_path):
    env = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    c = platforms.config_locations("win32", env, tmp_path)
    assert c[0] == tmp_path / "Roaming" / platforms.VERGE_APP_ID
    assert tmp_path / "Roaming" / "clash-verge-rev" in c
    assert tmp_path / "Local" / "clash-verge-rev" in c


def test_windows_missing_appdata_is_not_relative(tmp_path):
    c = platforms.config_locations("win32", {}, tmp_path)
    assert all(p.is_absolute() or str(p).startswith("C:") for p in c)
    assert c[0] == tmp_path / "AppData" / "Roaming" / platforms.VERGE_APP_ID


def test_linux_candidates_respect_xdg(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path / "data")}
    c = platforms.config_locations("linux", env, tmp_path)
    assert c[0] == tmp_path / "data" / platforms.VERGE_APP_ID


def test_resolve_order(tmp_path):
    env = {"CLASH_VERGE_DIR": str(tmp_path / "env")}
    assert platforms.locate_config_dir("/explicit", "linux", env, tmp_path) == Path("/explicit")
    assert platforms.locate_config_dir(None, "linux", env, tmp_path) == tmp_path / "env"


def test_resolve_prefers_existing_candidate(tmp_path):
    env = {"APPDATA": str(tmp_path / "Roaming")}
    config_dir = tmp_path / "Roaming" / "clash-verge-rev"
    config_dir.mkdir(parents=True)
    assert platforms.locate_config_dir(None, "win32", env, tmp_path) == config_dir


def test_resolve_falls_back_to_default(tmp_path):
    assert platforms.locate_config_dir(None, "linux", {}, tmp_path) == (
        tmp_path / ".local" / "share" / platforms.VERGE_APP_ID
    )


def test_executable_discovery_rejects_a_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(platforms.shutil, "which", lambda *args, **kwargs: str(tmp_path))
    assert platforms.find_verge_executable("linux", {}) is None


def test_restart_resolves_the_executable_before_any_host_mutation(monkeypatch):
    commands = []
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: None)
    monkeypatch.setattr(platforms, "_run_host_command", lambda *args: commands.append(args))
    with pytest.raises(OperationError) as error:
        platforms.restart_verge()
    assert error.value.code == "NOT_FOUND"
    assert commands == []


def test_restart_waits_for_exact_process_name_to_exit(monkeypatch):
    events = []
    codes = iter([0, 0, 1])

    def run_command(arguments, timeout):
        events.append(arguments)
        return next(codes)

    monkeypatch.setattr(platforms, "platform_name", lambda: "linux")
    monkeypatch.setattr(platforms.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: "/test/clash-verge")
    monkeypatch.setattr(platforms, "_run_host_command", run_command)
    monkeypatch.setattr(platforms.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(platforms.subprocess, "Popen", lambda arguments, **kwargs: events.append(arguments))
    platforms.restart_verge()
    assert events == [["pkill", "-TERM", "-u", "501", "-x", "clash-verge"],
                      ["pgrep", "-u", "501", "-x", "clash-verge"],
                      ["pgrep", "-u", "501", "-x", "clash-verge"], ["/test/clash-verge"]]


def test_restart_stops_after_a_failed_termination(monkeypatch):
    launched = []
    monkeypatch.setattr(platforms, "platform_name", lambda: "linux")
    monkeypatch.setattr(platforms.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: "/test/clash-verge")
    monkeypatch.setattr(platforms, "_run_host_command", lambda *args: 2)
    monkeypatch.setattr(platforms.subprocess, "Popen", lambda arguments, **kwargs: launched.append(arguments))
    with pytest.raises(OperationError) as error:
        platforms.restart_verge()
    assert error.value.code == "HOST_COMMAND_FAILED"
    assert launched == []


def test_windows_restart_can_start_an_app_that_is_not_running(monkeypatch):
    launched = []
    monkeypatch.setattr(platforms, "platform_name", lambda: "windows")
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: "/test/clash-verge.exe")
    monkeypatch.setattr(platforms, "_run_host_command", lambda *args: 128)
    monkeypatch.setattr(platforms.subprocess, "Popen", lambda arguments, **kwargs: launched.append(arguments))
    platforms.restart_verge()
    assert launched == [["/test/clash-verge.exe"]]


def test_file_manager_failure_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(platforms, "platform_name", lambda: "linux")
    monkeypatch.setattr(platforms, "_run_host_command", lambda *args: 1)
    with pytest.raises(OperationError) as error:
        platforms.open_directory(tmp_path)
    assert error.value.code == "HOST_COMMAND_FAILED"
