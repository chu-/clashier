"""Exercise live CLI behavior through local TCP and Unix socket controllers."""

import json
import os
import subprocess
import sys

import pytest
import yaml
from jsonschema import Draft202012Validator
from tests.conftest import GROUP, NODE_A, NODE_B, make_runner
from tests.support import write_yaml_document

from clashier.cli.main import clashier
from clashier.cli.protocol import load_schema


def configure(config_dir, address):
    config = yaml.safe_load((config_dir / "clash-verge.yaml").read_text(encoding="utf-8"))
    config["external-controller"] = address if address.startswith("http") else ""
    config["external-controller-unix"] = address[len("unix://"):] if address.startswith("unix://") else ""
    write_yaml_document(config_dir / "clash-verge.yaml", config)


def invoke(config_dir, *args, **kwargs):
    result = make_runner().invoke(
        clashier, ["--config-dir", str(config_dir), "--output", "json"] + list(args), **kwargs
    )
    value = json.loads(result.stdout)
    Draft202012Validator(load_schema("result")).validate(value)
    return result, value


@pytest.mark.parametrize("transport", ["tcp", "unix"])
def test_select_verify_persist_and_repeat(local_core, config_dir, transport, native_client):
    server = local_core(transport)
    configure(config_dir, server.address)
    native_client(server)
    args = ("proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist")
    result, value = invoke(config_dir, *args)
    assert result.exit_code == 0, result.output
    assert value["data"]["after"] == NODE_B
    assert value["data"]["persistence"]["status"] == "saved"
    Draft202012Validator(load_schema("proxy-select-result")).validate(value["data"])
    profile = yaml.safe_load((config_dir / "profiles.yaml").read_text(encoding="utf-8"))["items"][0]
    assert profile["selected"] == [{"name": GROUP, "now": NODE_B}]
    result, repeated = invoke(config_dir, *args)
    assert result.exit_code == 0
    assert repeated["data"]["status"] == "unchanged"
    assert repeated["data"]["changed"] is False
    assert server.writes == [NODE_B]


def test_default_select_is_runtime_only(local_core, config_dir):
    server = local_core()
    configure(config_dir, server.address)
    before = (config_dir / "profiles.yaml").read_bytes()
    result, value = invoke(config_dir, "proxy", "select", "--group", GROUP, "--name", NODE_B)
    assert result.exit_code == 0
    assert value["data"]["persistence"]["status"] == "not_requested"
    assert (config_dir / "profiles.yaml").read_bytes() == before


@pytest.mark.parametrize("transport", ["tcp", "unix"])
def test_list_and_probe_are_safe_and_do_not_select(local_core, config_dir, transport):
    server = local_core(transport)
    configure(config_dir, server.address)
    result, value = invoke(config_dir, "proxy", "list")
    assert result.exit_code == 0, result.output
    Draft202012Validator(load_schema("proxy-list-result")).validate(value["data"])
    nodes = {item["name"]: item for item in value["data"]["items"]}
    assert set(nodes) == {NODE_A, NODE_B, "DIRECT"}
    assert nodes[NODE_A]["groups"] == [GROUP]
    assert nodes[NODE_A]["selected_in"] == [GROUP]
    assert nodes[NODE_B]["selected_in"] == []
    assert "credential-sentinel" not in result.stdout
    assert "password-sentinel" not in result.stdout
    assert "private.example" not in result.stdout
    result, value = invoke(config_dir, "proxy", "list", "--group", GROUP)
    assert result.exit_code == 0
    assert "credential-sentinel" not in result.stdout
    assert "password-sentinel" not in result.stdout
    assert "private.example" not in result.stdout
    Draft202012Validator(load_schema("proxy-list-result")).validate(value["data"])
    result, measured = invoke(config_dir, "proxy", "probe", "--group", GROUP, "--name", NODE_A)
    assert result.exit_code == 0
    assert measured["data"]["status"] == "reachable"
    assert measured["data"]["latency_ms"] == 0
    Draft202012Validator(load_schema("proxy-probe-result")).validate(measured["data"])
    assert not server.writes


def test_stale_config_socket_falls_back_to_current_service(local_core, config_dir, monkeypatch, native_client):
    server = local_core("unix")
    configure(config_dir, "unix://" + str(server.socket_path.parent / "missing.sock"))
    monkeypatch.setenv("CLASH_VERGE_DIR", str(config_dir))
    monkeypatch.setattr("clashier.platforms.controller_sockets", lambda: [server.socket_path])
    native_client(server)
    result, value = invoke(config_dir, "proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist")
    assert result.exit_code == 0, result.output
    assert value["data"]["live_status"] == "verified"
    assert server.writes == [NODE_B]


def test_explicit_endpoint_never_falls_back(local_core, config_dir):
    server = local_core()
    configure(config_dir, server.address)
    result, value = invoke(config_dir, "--controller", "http://127.0.0.1:1", "--timeout", "0.2",
                           "proxy", "select", "--group", GROUP, "--name", NODE_B)
    assert result.exit_code == 1
    assert value["error"]["code"] == "CONTROLLER_UNAVAILABLE"
    assert not server.writes


def test_discovery_rejects_ambiguous_write(local_core, config_dir):
    tcp, unix = local_core(), local_core("unix")
    configure(config_dir, tcp.address)
    config = yaml.safe_load((config_dir / "clash-verge.yaml").read_text(encoding="utf-8"))
    config["external-controller-unix"] = str(unix.socket_path)
    write_yaml_document(config_dir / "clash-verge.yaml", config)
    result, discovered = invoke(config_dir, "core", "discover")
    assert result.exit_code == 0
    assert len(discovered["data"]["items"]) == 2
    result, value = invoke(config_dir, "proxy", "select", "--group", GROUP, "--name", NODE_B)
    assert result.exit_code == 1
    assert value["error"]["code"] == "AMBIGUOUS_TARGET"
    assert tcp.writes == unix.writes == []
    instance = discovered["data"]["items"][0]["instance_id"]
    result, value = invoke(config_dir, "--instance", instance, "proxy", "select", "--group", GROUP, "--name", NODE_B)
    assert result.exit_code == 0


def test_lost_response_is_reconciled_without_repeating_put(local_core, config_dir):
    server = local_core()
    configure(config_dir, server.address)
    server.drop_response = True
    result, value = invoke(config_dir, "proxy", "select", "--group", GROUP, "--name", NODE_B)
    assert result.exit_code == 0, result.output
    assert value["data"]["after"] == NODE_B
    assert server.writes == [NODE_B]


def test_subprocess_composition(local_core, config_dir, tmp_path):
    server = local_core()
    configure(config_dir, server.address)
    command = [sys.executable, "-m", "clashier", "--config-dir", str(config_dir),
               "--controller", server.address, "--output", "json"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    policy = """
import json, sys
choices = json.load(sys.stdin)
assert choices["ok"]
matches = [item for item in choices["data"]["items"] if item["name"] == sys.argv[1]]
assert len(matches) == 1
json.dump({"group": choices["data"]["group"], "name": matches[0]["name"], "persist": False,
           "if_current": choices["data"]["selected"],
           "context": {key: choices["context"][key] for key in ("instance_id", "profile_uid")}}, sys.stdout)
"""
    with subprocess.Popen(command + ["proxy", "list", "--group", GROUP], stdout=subprocess.PIPE,
                          cwd=tmp_path, env=env) as listing:
        with subprocess.Popen([sys.executable, "-c", policy, NODE_B], stdin=listing.stdout,
                              stdout=subprocess.PIPE, cwd=tmp_path, env=env) as builder:
            listing.stdout.close()
            selected = subprocess.run(command + ["proxy", "select", "--input-json", "-"], stdin=builder.stdout,
                                      cwd=tmp_path, env=env, capture_output=True, text=True,
                                      encoding="utf-8", check=True, timeout=10)
            builder.stdout.close()
            assert builder.wait(timeout=5) == 0
        assert listing.wait(timeout=5) == 0
    assert json.loads(selected.stdout)["data"]["after"] == NODE_B
    assert not selected.stderr
    assert server.writes == [NODE_B]
    failed = subprocess.run(command + ["proxy", "select", "--input-json", "-"], input="", cwd=tmp_path,
                            env=env, capture_output=True, text=True, encoding="utf-8")
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["error"]["code"] == "INVALID_ARGUMENT"
    assert failed.stderr
    assert server.writes == [NODE_B]


def test_disk_failure_relaunches_previous_choice_and_reports_partial(
    local_core, config_dir, monkeypatch, native_client
):
    server = local_core()
    configure(config_dir, server.address)

    def fail_write(*args):
        raise OSError("disk unavailable")

    native_client(server)
    monkeypatch.setattr("clashier.adapters.profiles.ProfileStore.set_selection", fail_write)
    result, value = invoke(config_dir, "proxy", "select", "--group", GROUP, "--name", NODE_B, "--persist")
    assert result.exit_code == 1
    assert value["error"]["code"] == "PERSISTENCE_FAILED"
    assert value["data"]["status"] == "partial"
    assert value["data"]["after"] is None
    assert value["data"]["live_status"] == "unknown"
    assert server.selected == NODE_A


def test_stale_profile_context_does_not_write(local_core, config_dir):
    server = local_core()
    configure(config_dir, server.address)
    _, listing = invoke(config_dir, "proxy", "list", "--group", GROUP)
    request = {"group": GROUP, "name": NODE_B, "context": {
        "instance_id": listing["context"]["instance_id"], "profile_uid": "other-profile"}}
    result, value = invoke(config_dir, "proxy", "select", "--input-json", "-", input=json.dumps(request))
    assert result.exit_code == 1
    assert value["error"]["code"] == "STALE_CONTEXT"
    assert not server.writes


@pytest.mark.parametrize("args,input_text", [
    (("proxy", "select", "--input-json", "-"), ""),
    (("proxy", "select", "--input-json", "-"), '{"group":"g","name":"n","persist":"yes"}'),
    (("proxy", "select", "--input-json", "-"), '{"group":"g","name":"n","typo":true}'),
    (("proxy", "select", "--group", "g", "--input-json", "-"), '{"group":"g","name":"n"}'),
    (("proxy", "list", "--group"), None),
])
def test_invalid_input_returns_json_without_connecting(config_dir, args, input_text):
    result, value = invoke(config_dir, *args, input=input_text)
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"
    assert value["context"] is None
    assert result.stderr
