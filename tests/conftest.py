import inspect
import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner as ClickRunner
from jsonschema import Draft202012Validator

from clashier.cli.main import clashier
from clashier.cli.protocol import load_schema
from tests.support import MockHTTP, write_yaml_document


def make_runner():
    """Keep stream assertions meaningful on Click 8.1 and 8.2+."""
    options = {"mix_stderr": False} if "mix_stderr" in inspect.signature(ClickRunner).parameters else {}
    return ClickRunner(**options)

GROUP = "🧪 Example Group / 示例 #1"
NODE_A = "🧪 Example Node A / 示例"
NODE_B = "🧪 Example Node B # 示例"
CONTROLLER_SECRET = "example-controller-secret-not-real"

@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Never let a test touch the real Clash Verge installation of the machine."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(fake_home))
    for var in ("APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(fake_home / var.lower()))
    monkeypatch.setenv("CLASH_VERGE_DIR", str(tmp_path / "default-config"))
    monkeypatch.delenv("CLASH_API_URL", raising=False)
    monkeypatch.delenv("CLASH_API_SECRET", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr("clashier.platforms.controller_sockets", lambda: [])
    return fake_home


@pytest.fixture
def config_dir(tmp_path):
    """Build fresh configured documents and matching content files for each test."""
    directory = tmp_path / "verge 测试配置"
    identities = [("p1", "Main", "remote"), ("p2", "Backup 订阅", "local")]
    records = [{"uid": uid, "name": name, "type": kind, "file": uid + ".yaml"}
               for uid, name, kind in identities]
    records[0].update(url="https://sub.example/a", selected=[{"name": GROUP, "now": NODE_A}],
                      extra={key: gib * 1024 ** 3 for key, gib in (("upload", 1), ("download", 2), ("total", 10))})
    documents = {
        "profiles.yaml": {"current": "p1", "items": records},
        "clash-verge.yaml": {
            "mixed-port": 7897, "external-controller": "127.0.0.1:9097", "secret": CONTROLLER_SECRET,
            "dns": {"enable": True, "nameserver": ["192.0.2.53"]},
            "proxies": [{"name": name, "type": "ss", "server": "node.invalid", "port": 443,
                         "password": "example-password-not-real"} for name in (NODE_A, NODE_B)],
            "proxy-groups": [{"name": name, "type": kind, "proxies": choices}
                             for name, kind, choices in ((GROUP, "select", [NODE_A, NODE_B, "DIRECT"]),
                                                         ("Auto", "url-test", [NODE_A, NODE_B]))],
            "rules": ["DOMAIN-SUFFIX,example.com,Proxy", "GEOIP,CN,DIRECT", "MATCH,Proxy"],
        },
        "verge.yaml": {
            "current_profile": "p1", "enable_system_proxy": False, "enable_tun_mode": False,
            "verge_mixed_port": 7897, "verge_port": 7899, "verge_socks_port": 7898,
            "verge_http_enabled": True, "web_ui_list": [{"name": "yacd", "url": "http://yacd.example"}],
        },
    }
    documents.update({"profiles/" + record["file"]: {"proxies": []} for record in records})
    for relative_path, document in documents.items():
        destination = directory / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_yaml_document(destination, document)
    return directory


@pytest.fixture
def run(config_dir, monkeypatch):
    for var in ("CLASH_VERGE_DIR", "CLASH_API_URL", "CLASH_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    runner = make_runner()

    def _run(*args, **kwargs):
        return runner.invoke(clashier, ["--config-dir", str(config_dir)] + list(args), **kwargs)

    return _run


@pytest.fixture
def json_run(run):
    def invoke(*args, **kwargs):
        result = run("--output", "json", *args, **kwargs)
        value = json.loads(result.stdout)
        Draft202012Validator(load_schema("result")).validate(value)
        return result, value

    return invoke


@pytest.fixture
def http(monkeypatch):
    """Use real request construction with an in-memory transport and deterministic replies."""
    recorder = MockHTTP()
    client_type = httpx.Client
    clients = []

    def create_client(*args, **options):
        options["transport"] = httpx.MockTransport(recorder)
        client = client_type(*args, **options)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", create_client)
    yield recorder
    for client in clients:
        client.close()
