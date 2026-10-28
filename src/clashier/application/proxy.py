"""Complete, reusable semantics for one proxy operation."""

from typing import Any, Dict, Optional

from clashier.application.ports import Runtime, SelectionMemory
from clashier.errors import ControllerError, OperationError
from clashier.models import SelectRequest, Snapshot


class ProxyControl:
    """Inspect, measure and select proxies without knowing HTTP or YAML."""

    def __init__(self, runtime: Runtime, memory: SelectionMemory):
        self.runtime = runtime
        self.memory = memory

    def context(self) -> Dict[str, Any]:
        """Describe the runtime/profile pair used by the operation."""
        return {"instance_id": self.runtime.instance_id, "profile_uid": self.memory.profile_uid()}

    def snapshot(self) -> Snapshot:
        """Read a sanitized live snapshot."""
        return self.runtime.api.snapshot()

    def list_proxies(self, group: Optional[str] = None) -> Dict[str, Any]:
        """List live nodes with direct memberships, or one group's candidates."""
        snapshot = self.snapshot()
        if group is None:
            available = dict(snapshot.nodes)
            for name, node in self.runtime.api.provider_proxies().items():
                available.setdefault(name, node)
            nodes = {name: dict(node, groups=[], selected_in=[]) for name, node in available.items()
                     if name not in snapshot.groups}
            for parent in snapshot.groups.values():
                for name in dict.fromkeys(parent.choices):
                    if name in nodes:
                        nodes[name]["groups"].append(parent.name)
                        if name == parent.selected:
                            nodes[name]["selected_in"].append(parent.name)
            return {"group": None, "selected": None, "type": "all", "writable": False,
                    "mode": snapshot.mode, "view": "live", "items": list(nodes.values())}
        if group not in snapshot.groups:
            raise OperationError("NOT_FOUND", "Group '{}' not found".format(group))
        selected = snapshot.groups[group]
        return {"group": group, "selected": selected.selected, "type": selected.kind, "view": "live",
                "writable": selected.writable,
                "items": [snapshot.nodes.get(name, {"name": name, "type": "unknown"})
                          for name in selected.choices]}

    def get(self, group: str) -> Dict[str, Any]:
        """Read the selected group chain, without claiming traffic verification."""
        snapshot = self.snapshot()
        if group not in snapshot.groups:
            raise OperationError("NOT_FOUND", "Group '{}' not found".format(group))
        chain = [group]
        current = group
        while current in snapshot.groups:
            current = snapshot.groups[current].selected
            if current is None:
                return {"group": group, "selected": snapshot.groups[group].selected,
                        "chain": chain, "resolved": False, "reason": "no_selection", "mode": snapshot.mode}
            if current in chain:
                return {"group": group, "selected": snapshot.groups[group].selected,
                        "chain": chain, "resolved": False, "reason": "cycle", "mode": snapshot.mode}
            chain.append(current)
        return {"group": group, "selected": snapshot.groups[group].selected,
                "chain": chain, "resolved": current in snapshot.nodes, "mode": snapshot.mode}

    def probe(self, group: str, name: str, url: str, timeout_ms: int) -> Dict[str, Any]:
        """Measure one exact candidate, leaving runtime selection unchanged."""
        target = self.runtime.api.read_group(group)
        if name not in target.choices:
            raise OperationError("NOT_FOUND", "Proxy '{}' is not in group '{}'".format(name, group))
        timeout_ms = min(timeout_ms, max(1, int(self.runtime.deadline.remaining() * 1000)))
        latency = self.runtime.api.delay(name, url, timeout_ms)
        return {"group": group, "name": name, "status": "timeout" if latency is None else "reachable",
                "latency_ms": latency, "url": url}

    def select(self, request: SelectRequest) -> Dict[str, Any]:
        """Set, verify and optionally remember one explicit selection."""
        if request.persist:
            self.memory.prepare()
        self._check_context(request.context)
        profile = self.memory.profile_uid()
        if request.persist and profile is None:
            raise OperationError("UNSUPPORTED_OPERATION", "No associated Verge profile; omit --persist")
        target = self.runtime.api.read_group(request.group)
        if not target.writable:
            raise OperationError("UNSUPPORTED_OPERATION", "Group does not support manual selection")
        if request.name not in target.choices:
            raise OperationError("NOT_FOUND", "Proxy '{}' is not in group '{}'".format(request.name, request.group))
        result = self._result(request, target.selected)
        if target.selected != request.name:
            if request.if_current is not None and target.selected != request.if_current:
                raise OperationError("PRECONDITION_FAILED", "Group selection changed", data=result)
            self._apply(request, result)
        else:
            result.update(status="unchanged", live_status="verified")
        if request.persist:
            self._persist(request, profile, result)
        self._verify(request, result)
        return result

    def _check_context(self, expected: Optional[Dict[str, Any]]) -> None:
        if expected is not None and expected != self.context():
            raise OperationError("STALE_CONTEXT", "Controller or profile context changed")

    @staticmethod
    def _result(request: SelectRequest, before: Optional[str]) -> Dict[str, Any]:
        return {"status": "not_applied", "changed": False, "group": request.group,
                "requested": request.name, "before": before, "after": before,
                "live_status": "not_applied", "persistence": {"requested": request.persist,
                "status": "not_requested"}, "traffic_verification": "not_performed"}

    def _apply(self, request: SelectRequest, result: Dict[str, Any]) -> None:
        try:
            self.runtime.api.select(request.group, request.name)
        except ControllerError as exc:
            if not exc.details["request_sent"]:
                exc.data = result
                raise
        self._verify(request, result, uncertain=True)
        result.update(status="applied", changed=True)

    def _verify(self, request: SelectRequest, result: Dict[str, Any], uncertain: bool = False) -> None:
        try:
            self.runtime.deadline.remaining()
            observed = self.runtime.api.read_group(request.group).selected
        except OperationError:
            result.update(status="unknown", changed=None, after=None, live_status="unknown")
            raise OperationError("OUTCOME_UNKNOWN", "Cannot verify live selection", data=result,
                                 needs_reconcile=True) from None
        result["after"] = observed
        if observed != request.name:
            result.update(status="unknown" if uncertain else "partial", changed=None, live_status="not_applied")
            raise OperationError("CONCURRENT_MODIFICATION", "Live selection does not match requested proxy",
                                 data=result, needs_reconcile=True)
        result["live_status"] = "verified"

    def _persist(self, request: SelectRequest, profile: str, result: Dict[str, Any]) -> None:
        try:
            saved = self.memory.save(request.group, request.name, profile)
        except OperationError as exc:
            result.update(status="partial")
            result["persistence"]["status"] = "failed"
            if exc.data and "client" in exc.data:
                result["persistence"]["client_activation"] = exc.data
                result.update(after=None, live_status="unknown", changed=None)
            raise OperationError("PERSISTENCE_FAILED", str(exc), data=result, needs_reconcile=True) from None
        result["persistence"].update({key: value for key, value in saved.items() if key != "changed"})
        if saved["changed"]:
            result.update(status="applied", changed=True)
