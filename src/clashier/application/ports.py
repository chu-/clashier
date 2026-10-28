"""The small dependency interfaces used by proxy operations."""

from typing import Any, Dict, Optional, Protocol

from clashier.models import Deadline, ProxyGroup, Snapshot


class Controller(Protocol):
    """Runtime operations supplied by mihomo or a controllable test adapter."""

    def snapshot(self) -> Snapshot: ...
    def provider_proxies(self) -> Dict[str, Dict[str, str]]: ...
    def read_group(self, name: str) -> ProxyGroup: ...
    def select(self, group: str, proxy: str) -> None: ...
    def delay(self, name: str, url: str, timeout_ms: int) -> Optional[int]: ...


class SelectionMemory(Protocol):
    """Commit a preference into the client and confirm its restored live selection."""

    def prepare(self) -> None: ...
    def profile_uid(self) -> Optional[str]: ...
    def save(self, group: str, name: str, expected_uid: str) -> Dict[str, Any]: ...


class Runtime(Protocol):
    """Resolve current access after persistence restarts the client and controller."""

    deadline: Deadline

    @property
    def api(self) -> Controller: ...

    @property
    def instance_id(self) -> str: ...
