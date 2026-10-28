import pytest
from tests.conftest import NODE_A, NODE_B
from tests.support import read_yaml_document, write_yaml_document

from clashier.errors import OperationError


@pytest.fixture
def wizard_runtime(verge_app, monkeypatch):
    monkeypatch.setattr("clashier.cli.wizard._terminal_available", lambda: True)
    return verge_app["selected"]


def test_choose_composes_selection_and_keeps_prompts_off_stdout(json_run, config_dir, wizard_runtime):
    result, value = json_run("choose", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 0, result.output
    assert value["data"]["after"] == NODE_B
    assert value["data"]["persistence"]["status"] == "saved"
    assert wizard_runtime == [NODE_B]
    assert "Profiles:" in result.stderr
    assert "Live candidates:" in result.stderr
    assert "Review selection:" in result.stderr
    assert "Current node" in result.stderr and "Requested node" in result.stderr
    assert "Remember selection" in result.stderr
    menu = result.stderr.split("Selected profile (configuration preview):")[0]
    assert "(p1)" not in menu and "(p2)" not in menu
    assert read_yaml_document(config_dir / "profiles.yaml")["items"][0]["selected"][0]["now"] == NODE_B


def test_choose_cancel_has_no_selection_write(run, wizard_runtime, http):
    result = run("choose", input="1\ny\n1\n2\nn\n")
    assert result.exit_code == 130
    assert wizard_runtime == [NODE_A]
    assert not any(request.method == "PUT" for request in http.requests)


def test_choose_inactive_profile_restarts_client(json_run, wizard_runtime, verge_app, http):
    result, value = json_run("choose", "--temporary", input="2\ny\n1\n2\ny\n")
    assert result.exit_code == 0, result.output
    assert verge_app["events"] == ["stop", ("start", "p2"), "ready"]
    assert result.stderr.index("Directly declared nodes:") < result.stderr.index("restart Clash Verge?")
    assert not any(request.method == "PUT" and request.url.path == "/configs" for request in http.requests)
    assert value["context"]["profile_uid"] == "p2"
    assert wizard_runtime == [NODE_B]


def test_human_wizard_emits_a_selection_summary_instead_of_json(run, wizard_runtime):
    result = run("choose", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 0
    assert "{" not in result.stdout
    assert "Selection: {} -> {}".format(NODE_A, NODE_B) in result.stdout
    assert "Live verification: verified" in result.stdout
    assert "Yes (restart to save)" in result.stderr


def test_choose_aborted_activation_does_not_change_profile(run, config_dir, wizard_runtime, http):
    before = (config_dir / "profiles.yaml").read_bytes()
    result = run("choose", input="2\nn\n")
    assert result.exit_code == 130
    assert (config_dir / "profiles.yaml").read_bytes() == before
    assert not http.requests


def test_choose_no_input_rejects_before_prompting(json_run, wizard_runtime, http):
    result, value = json_run("--no-input", "choose")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"
    assert not http.requests


def test_choose_requires_a_terminal(json_run, monkeypatch):
    monkeypatch.setattr("clashier.cli.wizard._terminal_available", lambda: False)
    result, value = json_run("choose")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"


def test_choose_stops_before_selection_if_client_is_not_ready(json_run, wizard_runtime, http, monkeypatch):
    def fail(self, deadline):
        raise OperationError("DEADLINE_EXCEEDED", "Client startup timed out")

    monkeypatch.setattr("clashier.platforms.VergeApp.wait_ready", fail)
    result, value = json_run("choose", input="1\ny\n")
    assert result.exit_code == 1
    assert value["data"]["client"]["status"] == "started"
    assert wizard_runtime == [NODE_A]
    assert not any(request.method == "PUT" for request in http.requests)


def test_prompt_reading_time_is_outside_operation_timeouts(json_run, wizard_runtime, monkeypatch):
    import click

    clock = [0.0]
    prompt = click.prompt
    monkeypatch.setattr("clashier.models.time.monotonic", lambda: clock[0])

    def slow_prompt(*args, **kwargs):
        value = prompt(*args, **kwargs)
        clock[0] += 30
        return value

    monkeypatch.setattr("clashier.cli.wizard.click.prompt", slow_prompt)
    result, value = json_run("choose", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 0
    assert value["data"]["after"] == NODE_B


def test_profile_change_after_confirmation_prevents_selection(
    json_run, config_dir, wizard_runtime, http, monkeypatch
):
    import click

    confirm = click.confirm

    def change_profile(*args, **kwargs):
        result = confirm(*args, **kwargs)
        if args[0].startswith("Apply this selection"):
            catalog = read_yaml_document(config_dir / "profiles.yaml")
            catalog["current"] = "p2"
            write_yaml_document(config_dir / "profiles.yaml", catalog)
        return result

    monkeypatch.setattr("clashier.cli.wizard.click.confirm", change_profile)
    result, value = json_run("choose", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 1
    assert value["error"]["code"] == "STALE_CONTEXT"
    assert not any(request.method == "PUT" for request in http.requests)


def test_profile_menu_does_not_render_saved_group_selections(run, wizard_runtime):
    result = run("choose", input="1\ny\n1\n2\nn\n")
    menu = result.stderr.split("Selected profile (configuration preview):")[0]
    assert NODE_A not in menu
    assert "'now':" not in menu


def test_shutdown_timeout_stops_before_writing_selection(json_run, config_dir, wizard_runtime, monkeypatch):
    before = (config_dir / "profiles.yaml").read_bytes()

    def slow_shutdown(self, timeout):
        raise OperationError("DEADLINE_EXCEEDED", "Client did not exit")

    monkeypatch.setattr("clashier.platforms.VergeApp.stop", slow_shutdown)
    result, value = json_run("choose", input="2\ny\n")
    assert result.exit_code == 1
    assert value["data"]["configuration"]["status"] == "not_saved"
    assert (config_dir / "profiles.yaml").read_bytes() == before


def test_client_start_failure_does_not_pretend_profile_was_loaded(json_run, wizard_runtime, monkeypatch):
    def fail(self):
        raise OperationError("HOST_COMMAND_FAILED", "Could not start client")

    monkeypatch.setattr("clashier.platforms.VergeApp.start", fail)
    result, value = json_run("choose", input="2\ny\n")
    assert result.exit_code == 1
    assert value["data"]["status"] == "partial"
    assert value["data"]["configuration"]["status"] == "saved"
    assert value["data"]["gui_sync"] == "not_verified"


def test_current_profile_is_restarted_even_if_graph_matches(json_run, wizard_runtime, verge_app):
    result, value = json_run("choose", "--temporary", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 0, result.output
    assert verge_app["events"] == ["stop", ("start", "p1"), "ready"]
    assert value["data"]["profile_activation"]["gui_sync"] == "restarted"


def test_startup_rediscovers_changed_controller(json_run, config_dir, wizard_runtime, http, monkeypatch):
    original_reply = http.reply

    def ready(self, deadline):
        core = read_yaml_document(config_dir / "clash-verge.yaml")
        core["external-controller"] = "192.0.2.10:9090"
        write_yaml_document(config_dir / "clash-verge.yaml", core)

    def reply(request):
        assert request.url.host == "192.0.2.10"
        return original_reply(request)

    monkeypatch.setattr("clashier.platforms.VergeApp.wait_ready", ready)
    http.reply = reply
    result, value = json_run("choose", input="1\ny\n1\n2\ny\n")
    assert result.exit_code == 0, result.output
    assert value["data"]["after"] == NODE_B
