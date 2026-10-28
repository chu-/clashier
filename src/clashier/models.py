"""Small types used across the proxy operation interface."""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from clashier.errors import OperationError


class Deadline:
    """Share one monotonic time budget across discovery and an operation."""

    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        """Return the remaining budget, or stop before starting another step."""
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise OperationError("DEADLINE_EXCEEDED", "Operation deadline exceeded")
        return remaining


@dataclass(frozen=True)
class Endpoint:
    """A controller address and its association with a local Verge profile."""

    address: str
    source: str
    profile_bound: bool = False
    secret: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def instance_id(self) -> str:
        """Identify an endpoint without exposing credentials or socket paths."""
        return "core-" + hashlib.sha256(self.address.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SelectRequest:
    """Set one explicit group's desired selection."""

    group: str
    name: str
    persist: bool = False
    if_current: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ProxyGroup:
    """A live group's selection and permitted candidates."""

    name: str
    kind: str
    selected: Optional[str]
    choices: List[str]

    @property
    def writable(self) -> bool:
        return self.kind.lower() == "selector"


@dataclass(frozen=True)
class Snapshot:
    """A running mode and a sanitized proxy graph."""

    mode: str
    groups: Dict[str, ProxyGroup]
    nodes: Dict[str, Dict[str, Any]]
