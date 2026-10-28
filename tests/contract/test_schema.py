"""The schemas shipped to callers must describe valid, stable contracts."""

import json

import pytest
from jsonschema import Draft202012Validator

from clashier.cli.protocol import load_schema


@pytest.mark.parametrize("name", ["result", "proxy-select-input", "proxy-select-result",
                                  "proxy-list-result", "proxy-probe-result"])
def test_published_schemas_are_valid(name):
    Draft202012Validator.check_schema(load_schema(name))


def test_schema_command_runs_without_configuration_or_controller(run):
    result = run("--config-dir", "/nonexistent-clash-config", "--output", "json", "schema", "show", "proxy.select")
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    Draft202012Validator(load_schema("result")).validate(value)
    assert value["context"] is None
    assert value["data"]["input"]["required"] == ["group", "name"]


def test_root_usage_error_uses_json(run):
    result = run("--output", "json", "--timeout", "bad", "proxy", "get")
    assert result.exit_code == 2
    value = json.loads(result.stdout)
    Draft202012Validator(load_schema("result")).validate(value)
    assert value["error"]["code"] == "INVALID_ARGUMENT"


def test_capabilities_describe_only_implemented_operations(run):
    result = run("--output", "json", "capabilities")
    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert "proxy.select" in data["operations"]
    assert data["named_pipe"] is False
