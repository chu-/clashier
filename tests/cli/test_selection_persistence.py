import json

import pytest
from tests.conftest import GROUP, NODE_A, NODE_B
from tests.support import read_yaml_document


def remembered(config_dir):
    profile = read_yaml_document(config_dir / "profiles.yaml")["items"][0]
    return next(item["now"] for item in profile["selected"] if item["name"] == GROUP)


@pytest.mark.parametrize("command, input_text", [
    (("proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist"), None),
    (("proxy", "select", "--input-json", "-"), json.dumps({"group": GROUP, "name": NODE_B, "persist": True})),
    (("choose",), "1\ny\n1\n2\ny\n"),
])
def test_persisted_node_survives_native_shutdown_and_next_start(
    json_run, config_dir, verge_app, monkeypatch, command, input_text
):
    monkeypatch.setattr("clashier.cli.wizard._terminal_available", lambda: True)
    result, value = json_run(*command, input=input_text)
    assert result.exit_code == 0, result.output
    assert value["data"]["persistence"]["status"] == "saved"
    assert value["data"]["persistence"]["gui_sync"] == "restarted"
    app = verge_app["app"]
    app.stop(30)
    assert remembered(config_dir) == NODE_B
    app.start()
    assert verge_app["selected"] == [NODE_B]
    app.stop(30)
    assert remembered(config_dir) == NODE_B


@pytest.mark.parametrize("command, input_text", [
    (("proxy", "select", "--group", GROUP, "--name", NODE_B), None),
    (("choose", "--temporary"), "1\ny\n1\n2\ny\n"),
])
def test_runtime_only_choice_preserves_saved_node_on_native_exit(
    json_run, config_dir, verge_app, monkeypatch, command, input_text
):
    monkeypatch.setattr("clashier.cli.wizard._terminal_available", lambda: True)
    result, value = json_run(*command, input=input_text)
    assert result.exit_code == 0, result.output
    assert value["data"]["persistence"]["status"] == "not_requested"
    assert verge_app["selected"] == [NODE_B]
    assert remembered(config_dir) == NODE_A
    verge_app["app"].stop(30)
    verge_app["app"].start()
    assert verge_app["selected"] == [NODE_A]


def test_persistence_is_not_successful_if_client_does_not_restore_the_saved_node(json_run, verge_app, monkeypatch):
    from clashier import platforms

    start = platforms.VergeApp.start

    def restore_wrong_node(self):
        start(self)
        verge_app["selected"][0] = NODE_A

    monkeypatch.setattr(platforms.VergeApp, "start", restore_wrong_node)
    result, value = json_run("--timeout", "0.3", "proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist")
    assert result.exit_code == 1
    assert value["data"]["persistence"]["status"] == "failed"
    assert value["data"]["persistence"]["client_activation"]["verification"]["reason"] == "saved_selection_not_observed"
    assert value["data"]["live_status"] == "unknown"


def test_removed_choose_persist_option_is_rejected_before_interaction(json_run, verge_app):
    result, value = json_run("choose", "--persist")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"
    assert verge_app["events"] == []


def test_explicit_timeout_is_not_reset_between_live_selection_and_persistence(
    json_run, verge_app, http, monkeypatch
):
    from clashier import platforms

    clock = [0.0]
    monkeypatch.setattr("clashier.models.time.monotonic", lambda: clock[0])
    reply = http.reply
    stop = platforms.VergeApp.stop

    def slow_write(request):
        if request.method == "PUT":
            clock[0] += 0.8
        return reply(request)

    def slow_stop(self, timeout):
        clock[0] += 0.3
        stop(self, timeout)

    http.reply = slow_write
    monkeypatch.setattr(platforms.VergeApp, "stop", slow_stop)
    result, value = json_run("--timeout", "1", "proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist")
    assert result.exit_code == 1
    assert value["data"]["persistence"]["status"] == "failed"
    assert value["data"]["persistence"]["client_activation"]["configuration"]["status"] == "failed"
    assert verge_app["events"] == ["stop", ("start", "p1")]
