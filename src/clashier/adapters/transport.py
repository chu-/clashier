"""HTTP client construction for TCP and Unix socket controllers."""

from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx

DEFAULT_CONTROLLER = "127.0.0.1:9097"
DEFAULT_TIMEOUT = 5.0
DEFAULT_DELAY_URL = "https://www.gstatic.com/generate_204"


def normalize_controller(address: Optional[str]) -> str:
    """Normalize a TCP URL or an absolute Unix socket address."""
    address = (address or DEFAULT_CONTROLLER).strip()
    if address.startswith("unix://"):
        path = address[len("unix://"):]
        if not Path(path).is_absolute():
            raise ValueError("Unix socket path must be absolute")
        return "unix://" + str(Path(path).resolve())
    if address.startswith(("http://", "https://")):
        return _http_address(address)
    if "://" in address or address.startswith("\\\\"):
        raise ValueError("Unsupported controller transport; use http(s):// or unix://")
    if address.startswith(":"):
        address = "127.0.0.1" + address
    host, sep, port = address.rpartition(":")
    if not sep:
        host, port = address, "9097"
    if host in ("", "0.0.0.0", "*"):  # noqa: S104 - connecting locally, never binding
        host = "127.0.0.1"
    elif host in ("[::]", "::"):
        host = "[::1]"
    return _http_address("http://{}:{}".format(host, port))


def _http_address(address: str) -> str:
    try:
        parsed = httpx.URL(address)
    except httpx.InvalidURL:
        raise ValueError("Invalid controller URL") from None
    if not parsed.host or parsed.username or parsed.password:
        raise ValueError("Controller URL must have a host and no embedded credentials")
    return str(parsed).rstrip("/")


def quote_name(name: str) -> str:
    """Encode a group or node name as one URL path segment."""
    return quote(name, safe="")


def make_client(address: str) -> httpx.Client:
    """Construct a synchronous client that ignores environment proxies."""
    socket_path = address[len("unix://"):] if address.startswith("unix://") else None
    transport = httpx.HTTPTransport(uds=socket_path, trust_env=False, retries=0)
    return httpx.Client(transport=transport, trust_env=False)
