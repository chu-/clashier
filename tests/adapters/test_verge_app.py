import json

import httpx
import pytest

from clashier import platforms
from clashier.errors import OperationError
from clashier.models import Deadline


@pytest.fixture
def client_app(config_dir, monkeypatch):
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: "/example/clash-verge")
    monkeypatch.setattr(platforms, "config_locations", lambda: [config_dir])
    (config_dir / "singleton-instance.json").write_text(json.dumps({
        "port": 12345, "token": "example-instance-token-not-real"}), encoding="utf-8")
    return platforms.VergeApp(config_dir)


def test_readiness_observes_core_availability_without_window_commands(client_app, http, monkeypatch):
    calls = []

    def reply(request):
        calls.append(request)
        assert request.url.path == "/commands/pac"
        assert "x-instance-token" not in request.headers
        return httpx.Response(503 if len(calls) == 1 else 200)

    http.reply = reply
    monkeypatch.setattr(platforms.time, "sleep", lambda seconds: None)
    client_app.wait_ready(Deadline(2))
    assert len(calls) == 2
    assert all(request.url.host == "127.0.0.1" for request in calls)


def test_readiness_does_not_follow_redirects_or_forward_auth(client_app, http):
    http.reply = httpx.Response(302, headers={"location": "https://example.com/"})
    with pytest.raises(OperationError) as error:
        client_app.wait_ready(Deadline(2))
    assert error.value.code == "HOST_COMMAND_FAILED"
    assert len(http.requests) == 1
    assert "example-instance-token" not in str(error.value)


def test_missing_instance_record_is_bounded_by_the_operation_deadline(client_app, config_dir, monkeypatch):
    (config_dir / "singleton-instance.json").unlink()
    clock = [0.0]
    monkeypatch.setattr("clashier.models.time.monotonic", lambda: clock[0])

    def advance(seconds):
        clock[0] += seconds

    monkeypatch.setattr(platforms.time, "sleep", advance)
    with pytest.raises(OperationError) as error:
        client_app.wait_ready(Deadline(0.2))
    assert error.value.code == "DEADLINE_EXCEEDED"


def test_client_restart_rejects_an_unrelated_configuration_directory(client_app, tmp_path):
    with pytest.raises(OperationError) as error:
        platforms.VergeApp(tmp_path / "another-instance")
    assert error.value.code == "UNSUPPORTED_OPERATION"


def test_launch_detaches_client_output_from_the_cli(client_app, monkeypatch):
    monkeypatch.setattr(platforms, "platform_name", lambda: "linux")
    calls = []
    monkeypatch.setattr(platforms.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
    client_app.start()
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["stdout"] == platforms.subprocess.DEVNULL
    assert calls[0][1]["stderr"] == platforms.subprocess.DEVNULL


def test_two_startup_checks_do_not_create_extra_windows(client_app, http, monkeypatch):
    monkeypatch.setattr(platforms.time, "sleep", lambda seconds: None)
    windows_per_start = []
    for _ in range(2):
        windows = [0]
        requests = [0]

        def during_startup(request):
            requests[0] += 1
            if request.url.path == "/commands/visible":
                # Native show_main_window can create a window before normal initialization.
                windows[0] += 1
            if requests[0] == 1:
                windows[0] += 1  # Normal startup finishes its own window creation.
            return httpx.Response(200 if request.url.path == "/commands/visible" or requests[0] > 1 else 503)

        http.reply = during_startup
        client_app.wait_ready(Deadline(2))
        windows_per_start.append(windows[0])
    assert windows_per_start == [1, 1]


def test_macos_launch_creates_a_process_even_if_system_launcher_only_acknowledges(client_app, monkeypatch):
    monkeypatch.setattr(platforms, "platform_name", lambda: "macos")
    monkeypatch.setattr(platforms.os, "getuid", lambda: 501, raising=False)
    client_app.executable = "/Applications/Clash Verge.app/Contents/MacOS/clash-verge"
    processes = []

    def direct_launch(*args, **kwargs):
        processes.append("running instance")

    def host_command(arguments, timeout):
        if arguments[0] == "pgrep":
            assert arguments == ["pgrep", "-u", "501", "-x", "clash-verge"]
            return 0 if processes else 1
        # Successful dispatch by open does not establish that a process was started.
        return 0

    monkeypatch.setattr(platforms.subprocess, "Popen", direct_launch)
    monkeypatch.setattr(platforms, "_run_host_command", host_command)
    client_app.start()
    client_app.start()
    assert processes == ["running instance"]


def test_failed_macos_process_check_does_not_spawn_another_instance(client_app, monkeypatch):
    monkeypatch.setattr(platforms, "platform_name", lambda: "macos")
    client_app.executable = "/Applications/Clash Verge.app/Contents/MacOS/clash-verge"
    monkeypatch.setattr(platforms.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(platforms, "_run_host_command", lambda *args: 2)
    direct_launches = []
    monkeypatch.setattr(platforms.subprocess, "Popen", lambda *args, **kwargs: direct_launches.append(args))
    with pytest.raises(OperationError) as error:
        client_app.start()
    assert error.value.code == "HOST_COMMAND_FAILED"
    assert direct_launches == []
