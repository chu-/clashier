"""Disposable local controllers: no tests touch the user's Clash installation."""

import json
import os
import socket
import socketserver
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from tests.conftest import GROUP, NODE_A, NODE_B
from tests.support import native_client_model, write_yaml_document


class ControllerHandler(BaseHTTPRequestHandler):
    """A small stateful controller that exercises the real transport."""

    def log_message(self, *args):
        pass

    def reply(self, status, value=None):
        body = json.dumps(value).encode("utf-8") if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/version":
            self.reply(200, {"version": "test-1.0"})
        elif path == "/configs":
            self.reply(200, {"mode": getattr(self.server, "mode", "rule")})
        elif path == "/proxies":
            if hasattr(self.server, "graph"):
                self.reply(200, {"proxies": self.server.graph})
                return
            self.reply(200, {"proxies": {
                GROUP: self.server.group(),
                NODE_A: {"type": "VLESS", "uuid": "credential-sentinel", "password": "password-sentinel"},
                NODE_B: {"type": "VLESS", "server": "private.example"},
                "DIRECT": {"type": "Direct"}}})
        elif path == "/providers/proxies":
            document = self.server.reloads[-1] if self.server.reloads else {}
            self.reply(200, {"providers": {name: {} for name in document.get("proxy-providers", {})}})
        elif path.startswith("/proxies/"):
            name = unquote(path[len("/proxies/"):])
            if hasattr(self.server, "graph") and name in self.server.graph:
                self.reply(200, self.server.graph[name])
                return
            if path.endswith("/delay"):
                self.reply(200, {"delay": self.server.latency})
            elif unquote(path[len("/proxies/"):]) == GROUP:
                self.reply(200, self.server.group())
            else:
                self.reply(404, {"message": "not found"})
        else:
            self.reply(404, {"message": "not found"})

    def do_PUT(self):
        if urlsplit(self.path).path == "/configs":
            document = yaml.safe_load(json.loads(self.rfile.read(int(self.headers["Content-Length"])))["payload"])
            self.server.reloads.append(document)
            self.server.mode = document.get("mode", "rule")
            kinds = {"select": "Selector", "url-test": "URLTest", "ss": "Shadowsocks", "vless": "VLESS"}
            graph = {item["name"]: {"type": kinds.get(item["type"], item["type"])}
                     for item in document.get("proxies") or []}
            graph["DIRECT"] = {"type": "Direct"}
            for item in document.get("proxy-groups") or []:
                choices = item.get("proxies") or []
                selected = self.server.selected if self.server.selected in choices else next(iter(choices), None)
                graph[item["name"]] = {"type": kinds.get(item["type"], item["type"]),
                                      "now": selected, "all": choices}
            self.server.graph = graph
            self.reply(204)
            return
        group = unquote(urlsplit(self.path).path[len("/proxies/"):])
        if hasattr(self.server, "graph"):
            target = self.server.graph.get(group)
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not target or payload["name"] not in target.get("all", []):
                self.reply(404, {"message": "not found"})
                return
            target["now"] = payload["name"]
            if group == GROUP:
                self.server.selected = payload["name"]
            self.server.writes.append(payload["name"])
            self.reply(204)
            return
        if group != GROUP:
            self.reply(404, {"message": "not found"})
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if payload["name"] not in (NODE_A, NODE_B, "DIRECT"):
            self.reply(400, {"message": "unknown candidate"})
            return
        self.server.selected = payload["name"]
        self.server.writes.append(payload["name"])
        if self.server.drop_response:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
        else:
            self.reply(204)


@contextmanager
def running_controller(transport):
    if transport == "unix" and os.name == "nt":
        pytest.skip("The Unix transport is supported on macOS and Linux")
    with tempfile.TemporaryDirectory(prefix="cv-", dir="/tmp" if os.name != "nt" else None) as temp:
        if transport == "unix":
            if not hasattr(socketserver, "UnixStreamServer"):
                pytest.skip("Unix sockets are unavailable")

            class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
                daemon_threads = True

            path = Path(temp) / "core.sock"
            server = UnixServer(str(path), ControllerHandler)
            server.address = "unix://" + str(path.resolve())
            server.socket_path = path
        else:
            server = ThreadingHTTPServer(("127.0.0.1", 0), ControllerHandler)
            server.address = "http://127.0.0.1:{}".format(server.server_port)
        server.selected = NODE_A
        server.latency = 0
        server.writes = []
        server.reloads = []
        server.drop_response = False
        server.group = lambda: {"name": GROUP, "type": "Selector", "now": server.selected,
                                "all": [NODE_A, NODE_B, "DIRECT"]}
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


@pytest.fixture
def local_core():
    with ExitStack() as stack:
        yield lambda transport="tcp": stack.enter_context(running_controller(transport))


@pytest.fixture
def native_client(config_dir, monkeypatch):
    """Run selection restoration against the real disposable HTTP/Unix controller."""
    document = {
        "proxies": [{"name": name, "type": "vless"} for name in (NODE_A, NODE_B)],
        "proxy-groups": [{"name": GROUP, "type": "select", "proxies": [NODE_A, NODE_B, "DIRECT"]}],
    }

    def install(server):
        for uid in ("p1", "p2"):
            write_yaml_document(config_dir / "profiles" / (uid + ".yaml"), document)

        def restore(remembered):
            if GROUP in remembered:
                server.selected = remembered[GROUP]

        app, events = native_client_model(config_dir, restore)
        monkeypatch.setattr("clashier.platforms.VergeApp", app)
        return events

    return install
