from tests.support import read_yaml_document, write_yaml_document

from clashier.errors import OperationError


def test_activation_saves_target_after_exit_and_lets_client_generate_config(json_run, verge_app, http):
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 0, result.output
    assert verge_app["events"] == ["stop", ("start", "p2"), "ready"]
    assert value["data"]["gui_sync"] == "restarted"
    assert value["data"]["client"]["status"] == "ready"
    assert value["data"]["verification"]["scope"] == "client_generated_proxy_graph"
    assert all(request.method == "GET" for request in http.requests)


def test_stop_failure_does_not_save_target_or_start_another_client(json_run, config_dir, verge_app, monkeypatch):
    before = (config_dir / "profiles.yaml").read_bytes()

    def fail(self, timeout):
        raise OperationError("DEADLINE_EXCEEDED", "Client did not exit")

    monkeypatch.setattr("clashier.platforms.VergeApp.stop", fail)
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "DEADLINE_EXCEEDED"
    assert value["data"]["configuration"]["status"] == "not_saved"
    assert (config_dir / "profiles.yaml").read_bytes() == before
    assert verge_app["events"] == []


def test_saving_failure_relaunches_client_with_existing_profile(json_run, verge_app, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("clashier.adapters.profiles.ProfileStore.activate", fail)
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "PERSISTENCE_FAILED"
    assert verge_app["events"] == ["stop", ("start", "p1")]
    assert value["data"]["client"]["status"] == "started"


def test_readiness_failure_reports_saved_selection_without_claiming_gui_sync(json_run, verge_app, monkeypatch):
    def fail(self, deadline):
        raise OperationError("APP_NOT_READY", "Client did not become ready")

    monkeypatch.setattr("clashier.platforms.VergeApp.wait_ready", fail)
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 1
    assert value["data"]["status"] == "partial"
    assert value["data"]["configuration"]["status"] == "saved"
    assert value["data"]["gui_sync"] != "restarted"


def test_startup_retries_reads_with_a_newly_generated_controller(json_run, config_dir, verge_app, http):
    import httpx

    reply = http.reply
    old_reads = []

    def restarting(request):
        if request.url.host == "127.0.0.1":
            old_reads.append(True)
            core = read_yaml_document(config_dir / "clash-verge.yaml")
            core["external-controller"] = "192.0.2.10:9090"
            write_yaml_document(config_dir / "clash-verge.yaml", core)
            raise httpx.ConnectError("old controller closed")
        return reply(request)

    http.reply = restarting
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 0, result.output
    assert old_reads == [True]
    assert value["data"]["status"] == "verified"
    assert verge_app["events"].count("stop") == 1
    assert all(request.method == "GET" for request in http.requests)


def test_startup_waits_for_client_generation_before_matching_an_old_graph(
    json_run, verge_app, monkeypatch
):
    from clashier import platforms

    start = platforms.VergeApp.start
    delays = []

    def generate_later(seconds):
        delays.append(seconds)
        start(None)

    monkeypatch.setattr(platforms.VergeApp, "start", lambda self: None)
    monkeypatch.setattr("clashier.application.profiles.time.sleep", generate_later)
    result, value = json_run("profile", "activate", "p2")
    assert result.exit_code == 0, result.output
    assert delays
    assert value["data"]["verification"]["status"] == "matched"


def test_client_activation_rejects_an_unassociated_explicit_controller(json_run, verge_app, http):
    result, value = json_run("--controller", "http://192.0.2.20:9090", "profile", "activate", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert verge_app["events"] == []
    assert not http.requests


def test_client_restart_budget_has_room_for_graceful_shutdown_and_respects_override(
    json_run, verge_app, monkeypatch
):
    from clashier import platforms

    budgets = []
    stop = platforms.VergeApp.stop

    def timed_stop(self, timeout):
        budgets.append(timeout)
        stop(self, timeout)

    monkeypatch.setattr(platforms.VergeApp, "stop", timed_stop)
    assert json_run("profile", "activate", "p2")[0].exit_code == 0
    assert json_run("--timeout", "10", "profile", "activate", "p1")[0].exit_code == 0
    assert 25 < budgets[0] <= 30
    assert 5 < budgets[1] <= 10
