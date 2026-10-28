import os
from pathlib import Path

import pytest


def test_logs_read_and_search(json_run, config_dir):
    logs = config_dir / "logs"
    logs.mkdir()
    old = logs / "old.log"
    old.write_text("old line\n", encoding="utf-8")
    os.utime(str(old), (1, 1))
    (logs / "new.log").write_text("".join("line {} 错误\n".format(i) for i in range(10)), encoding="utf-8")
    result, value = json_run("logs", "read", "--lines", "3")
    assert result.exit_code == 0
    assert value["data"]["items"] == ["line 7 错误", "line 8 错误", "line 9 错误"]
    assert len(json_run("logs", "search", "错误")[1]["data"]["items"]) == 10


def test_health_requires_an_explicit_url(json_run):
    result, value = json_run("health")
    assert result.exit_code == 2
    assert value["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com", "http://127.0.0.1:bad"])
def test_invalid_urls_are_structured_usage_errors(json_run, url):
    for args in (("health", "--url", url), ("profile", "add", url)):
        result, value = json_run(*args)
        assert result.exit_code == 2
        assert value["error"]["code"] == "INVALID_ARGUMENT"


def test_unreadable_log_is_not_reported_as_empty(json_run, config_dir, monkeypatch):
    logs = config_dir / "logs"
    logs.mkdir()
    (logs / "latest.log").write_text("entry\n", encoding="utf-8")

    def denied(*args, **kwargs):
        raise PermissionError("cannot read log")

    monkeypatch.setattr(Path, "open", denied)
    result, value = json_run("logs", "read")
    assert result.exit_code == 1
    assert value["error"]["code"] == "CONFIGURATION_ERROR"
