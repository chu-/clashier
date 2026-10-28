import json

import httpx
import pytest
from tests.conftest import GROUP, NODE_A, NODE_B
from tests.support import native_client_model, write_yaml_document


@pytest.fixture
def verge_app(config_dir, monkeypatch, http):
    """Model the real client's exit-time save and startup configuration generation."""
    document = {
        "mode": "rule",
        "proxies": [{"name": name, "type": "vless"} for name in (NODE_A, NODE_B)],
        "proxy-groups": [{"name": GROUP, "type": "select", "proxies": [NODE_A, NODE_B]}],
    }
    for uid in ("p1", "p2"):
        write_yaml_document(config_dir / "profiles" / (uid + ".yaml"), document)
    selected = [NODE_A]
    def restore(remembered):
        if GROUP in remembered:
            selected[0] = remembered[GROUP]

    App, events = native_client_model(config_dir, restore)

    def reply(request):
        if request.url.path == "/configs":
            return httpx.Response(204) if request.method == "PUT" else httpx.Response(200, json={"mode": "rule"})
        if request.method == "PUT":
            selected[0] = json.loads(request.content)["name"]
            return httpx.Response(204)
        group = {"type": "Selector", "now": selected[0], "all": [NODE_A, NODE_B]}
        return httpx.Response(200, json={"proxies": {
            GROUP: group, NODE_A: {"type": "VLESS"}, NODE_B: {"type": "VLESS"}}}
            if request.url.path == "/proxies" else group)

    monkeypatch.setattr("clashier.platforms.VergeApp", App)
    http.reply = reply
    return {"events": events, "selected": selected, "app": App(config_dir)}
