"""Shared test document I/O and an in-process HTTPX request recorder."""

from copy import deepcopy
from pathlib import Path

import httpx
import yaml


def read_yaml_document(path: Path):
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def write_yaml_document(path: Path, document) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        yaml.safe_dump(document, destination, allow_unicode=True, sort_keys=False)


def native_client_model(config_dir, restore):
    """Model native memory, exit-time catalog saving and generated configuration."""
    events = []
    loaded = [read_yaml_document(config_dir / "profiles.yaml")]

    class App:
        def __init__(self, directory):
            assert directory == config_dir

        def stop(self, timeout):
            events.append("stop")
            write_yaml_document(config_dir / "profiles.yaml", loaded[0])

        def start(self):
            catalog = read_yaml_document(config_dir / "profiles.yaml")
            loaded[0] = deepcopy(catalog)
            current = catalog["current"]
            events.append(("start", current))
            profile = next(item for item in catalog["items"] if item["uid"] == current)
            document = read_yaml_document(config_dir / "profiles" / profile["file"])
            core = read_yaml_document(config_dir / "clash-verge.yaml")
            core.update(document)
            write_yaml_document(config_dir / "clash-verge.yaml", core)
            restore({item["name"]: item["now"] for item in profile.get("selected") or []})

        def wait_ready(self, deadline):
            deadline.remaining()
            events.append("ready")

    return App, events


class MockHTTP:
    """Serve a response or request callback and retain the real HTTPX requests."""

    def __init__(self):
        self.requests = []
        self.reply = httpx.Response(404, json={"message": "No test response configured"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.reply(request) if callable(self.reply) else self.reply
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
