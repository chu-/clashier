"""Typed failure handling around the mihomo controller protocol."""

from typing import Any, Dict, Optional, Set

import httpx

from clashier.adapters.transport import (
    DEFAULT_DELAY_URL,
    DEFAULT_TIMEOUT,
    make_client,
    normalize_controller,
    quote_name,
)
from clashier.errors import ControllerError
from clashier.models import Deadline, ProxyGroup, Snapshot


class Mihomo:
    """Control one mihomo instance over TCP or a Unix domain socket."""

    def __init__(self, base_url: Optional[str] = None, secret: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, session: Optional[httpx.Client] = None,
                 deadline: Optional[Deadline] = None):
        self.address = normalize_controller(base_url)
        self.base_url = "http://localhost" if self.address.startswith("unix://") else self.address
        self.secret = secret
        self.timeout = timeout
        self.deadline = deadline
        self.session = session or make_client(self.address)

    def close(self) -> None:
        """Release client connections."""
        self.session.close()

    def headers(self) -> Dict[str, str]:
        """Supply authentication without exposing it in result data."""
        result = {"Accept": "application/json"}
        if self.secret and not self.address.startswith("unix://"):
            result["Authorization"] = "Bearer {}".format(self.secret)
        return result

    def request(self, method: str, path: str, timeout: Optional[float] = None, **kwargs: Any) -> Any:
        """Send one request; adapters never automatically retry writes."""
        budget = self.timeout if timeout is None else timeout
        if self.deadline:
            budget = min(budget, self.deadline.remaining())
        try:
            response = self.session.request(method, self.base_url + path,
                                            headers=self.headers(), timeout=budget, **kwargs)
        except httpx.ConnectError as exc:
            code = "PERMISSION_DENIED" if _permission_error(exc) else "CONTROLLER_UNAVAILABLE"
            raise ControllerError("Cannot connect to Clash API at {} (is Clash Verge running?)".format(
                self.address), code=code) from None
        except httpx.TimeoutException as exc:
            sent = method == "PUT" and not isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout))
            raise ControllerError("Clash API timed out ({})".format(self.address),
                                  code="DEADLINE_EXCEEDED", request_sent=sent) from None
        except httpx.TransportError:
            raise ControllerError("Clash API transport failed ({})".format(self.address),
                                  request_sent=method == "PUT") from None
        if response.status_code >= 400:
            self._raise_response_error(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            data = response.json()
        except ValueError:
            raise ControllerError("Clash API returned invalid JSON", code="INVALID_RESPONSE",
                                  request_sent=method == "PUT") from None
        if not isinstance(data, dict):
            raise ControllerError("Clash API returned a non-object response", code="INVALID_RESPONSE",
                                  request_sent=method == "PUT")
        return data

    @staticmethod
    def _raise_response_error(response: httpx.Response) -> None:
        status = response.status_code
        codes = {401: "AUTH_FAILED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}
        if status == 401:
            raise ControllerError("Clash API rejected the secret (401 Unauthorized)", 401, code="AUTH_FAILED")
        try:
            payload = response.json()
            message = payload.get("message", "") if isinstance(payload, dict) else ""
        except ValueError:
            message = ""
        raise ControllerError("Clash API error {}{}".format(status, ": " + str(message) if message else ""),
                              status, code=codes.get(status, "CONTROLLER_REJECTED"))

    def version(self) -> Dict[str, Any]:
        """Read the controller version."""
        return self.request("GET", "/version") or {}

    def configs(self) -> Dict[str, Any]:
        """Read running configuration."""
        return self.request("GET", "/configs") or {}

    def load_config(self, contents: str) -> None:
        """Hot-load a complete configuration without restarting the GUI process."""
        try:
            result = self.request("PUT", "/configs", params={"force": "true"}, json={"payload": contents})
            if result is not None:
                raise ControllerError("Unexpected configuration reload response", code="INVALID_RESPONSE",
                                      request_sent=True)
        except ControllerError as error:
            raise ControllerError("Core configuration reload failed{}".format(
                " (HTTP {})".format(error.status) if error.status is not None else ""),
                error.status, code=error.code, request_sent=error.details["request_sent"]) from None

    def provider_names(self) -> Set[str]:
        """Project configured provider identities without exposing their connection data."""
        return set(self._providers())

    def provider_proxies(self) -> Dict[str, Dict[str, str]]:
        """Project loaded provider nodes that may be absent from the main proxy map."""
        nodes = {}
        for provider in self._providers().values():
            if not isinstance(provider, dict):
                raise ControllerError("Invalid proxy provider entry", code="INVALID_RESPONSE")
            entries = provider.get("proxies")
            if entries is None:
                continue
            if not isinstance(entries, list):
                raise ControllerError("Invalid provider proxy list", code="INVALID_RESPONSE")
            for node in entries:
                if not isinstance(node, dict) or not all(isinstance(node.get(key), str) for key in ("name", "type")):
                    raise ControllerError("Invalid provider proxy entry", code="INVALID_RESPONSE")
                nodes.setdefault(node["name"], {"name": node["name"], "type": node["type"]})
        return nodes

    def _providers(self) -> Dict[str, Any]:
        providers = (self.request("GET", "/providers/proxies") or {}).get("providers")
        if not isinstance(providers, dict):
            raise ControllerError("Invalid proxy provider response", code="INVALID_RESPONSE")
        return providers

    def proxies(self) -> Dict[str, Any]:
        """Read the live proxy graph."""
        graph = (self.request("GET", "/proxies") or {}).get("proxies")
        if not isinstance(graph, dict):
            raise ControllerError("Clash API returned an invalid proxy graph", code="INVALID_RESPONSE")
        return graph

    def proxy(self, name: str) -> Dict[str, Any]:
        """Read one proxy or group."""
        return self.request("GET", "/proxies/" + quote_name(name)) or {}

    def read_group(self, name: str) -> ProxyGroup:
        """Parse one group's live state at the external response boundary."""
        try:
            return _parse_group(name, self.proxy(name))
        except ControllerError as exc:
            if exc.status == 404:
                raise ControllerError("Group '{}' not found".format(name), 404, code="NOT_FOUND") from None
            raise

    def snapshot(self) -> Snapshot:
        """Return only the runtime fields needed for proxy operations."""
        config = self.configs()
        graph = self.proxies()
        if not isinstance(graph, dict) or not isinstance(config.get("mode"), str):
            raise ControllerError("Invalid runtime proxy graph or mode", code="INVALID_RESPONSE")
        groups = {}
        nodes = {}
        for name, value in graph.items():
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                raise ControllerError("Invalid proxy entry", code="INVALID_RESPONSE")
            nodes[name] = {"name": name, "type": value["type"]}
            if "all" in value:
                groups[name] = _parse_group(name, value)
        return Snapshot(config["mode"], groups, nodes)

    def select(self, group: str, proxy: str) -> None:
        """Request a selection; application operations verify its effect."""
        self.request("PUT", "/proxies/" + quote_name(group), json={"name": proxy})

    def delay(self, name: str, url: str = DEFAULT_DELAY_URL, timeout_ms: int = 5000) -> Optional[int]:
        """Measure latency, preserving zero as a valid measurement."""
        try:
            data = self.request("GET", "/proxies/{}/delay".format(quote_name(name)),
                                params={"url": url, "timeout": timeout_ms},
                                timeout=timeout_ms / 1000.0 + self.timeout)
        except ControllerError as exc:
            if exc.status in (408, 503, 504):
                return None
            raise
        value = (data or {}).get("delay")
        if value is not None and (type(value) is not int or value < 0):
            raise ControllerError("Clash API returned an invalid delay", code="INVALID_RESPONSE")
        return value


def _permission_error(exc: BaseException) -> bool:
    while exc is not None:
        if isinstance(exc, PermissionError):
            return True
        exc = exc.__cause__
    return False


def _parse_group(name: str, value: Dict[str, Any]) -> ProxyGroup:
    choices = value.get("all")
    if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
        raise ControllerError("Invalid proxy group '{}'".format(name), code="INVALID_RESPONSE")
    kind, selected = value.get("type"), value.get("now")
    if not isinstance(kind, str) or (selected is not None and not isinstance(selected, str)):
        raise ControllerError("Invalid proxy group '{}'".format(name), code="INVALID_RESPONSE")
    return ProxyGroup(name, kind, selected, choices)
