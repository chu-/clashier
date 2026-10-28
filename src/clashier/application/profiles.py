"""Profile activation and explicitly scoped runtime observations."""

import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import yaml

from clashier import platforms
from clashier.adapters.profile_config import render_profile_config
from clashier.adapters.profiles import describe_profile
from clashier.adapters.yaml_files import write_mapping
from clashier.errors import ControllerError, OperationError

if TYPE_CHECKING:
    from clashier.bootstrap import Bootstrap


class ProfileControl:
    """Coordinate configured profiles with their associated live controller."""

    def __init__(self, state: "Bootstrap"):
        self.state = state
        self._app: Optional[platforms.VergeApp] = None

    def prepare(self) -> None:
        """Resolve the client before a persistent operation changes the live node."""
        if not self.state.explicit_timeout:
            self.state.renew_deadline(30.0)
        self._app = platforms.VergeApp(self.state.store.config_dir)

    def profile_uid(self) -> Optional[str]:
        """Identify the profile associated with the current controller."""
        current = self.state.store.profiles.current() if self.state.endpoint.profile_bound else None
        return current["uid"] if current else None

    def save(self, group: str, name: str, expected_uid: str) -> Dict[str, Any]:
        """Load the saved choice into the client's memory and verify restored runtime."""
        activation = None
        try:
            current = self.state.store.profiles.current()
            if not current or current["uid"] != expected_uid:
                raise OperationError("STALE_CONTEXT", "Profile changed before saving selection")
            before = {item["name"]: item["now"] for item in current.get("selected") or []}
            activation = self.activate(expected_uid, selection=(group, name))
            current = self.state.store.profiles.current()
            saved = {item["name"]: item["now"] for item in (current or {}).get("selected") or []}
            if not current or current["uid"] != expected_uid or saved.get(group) != name:
                raise OperationError("PERSISTENCE_FAILED", "Client did not retain the saved node", data=activation)
            return {"changed": before.get(group) != name, "status": "saved", "method": "client_restart",
                    "gui_sync": activation["gui_sync"], "client": activation["client"]}
        except (OSError, yaml.YAMLError) as error:
            raise OperationError("PERSISTENCE_FAILED", "Cannot read saved selection", data=activation) from error

    def activate(self, identity: str, *, core_only: bool = False,
                 selection: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
        """Restart the official client by default; core-only reload is explicit."""
        if core_only:
            return self._activate_core(identity)
        if selection is None:
            self.state.renew_deadline(self.state.timeout if self.state.explicit_timeout else 30.0)
        entry, document = self.state.store.profiles.document(identity)
        describe_profile(entry, document)
        app = self._app if self._app is not None else platforms.VergeApp(self.state.store.config_dir)
        endpoints = self.state.endpoints()
        if any(item.source == "explicit" and not item.profile_bound for item in endpoints) or (
            self.state.instance and not any(item.instance_id == self.state.instance and item.profile_bound
                                            for item in endpoints)
        ):
            raise OperationError("UNSUPPORTED_OPERATION", "Client restart requires its associated local controller")
        result = {"status": "not_applied", "profile_uid": entry["uid"], "name": entry.get("name"),
                  "source": "configured", "reload": {"status": "not_requested", "method": "client_restart"},
                  "configuration": {"status": "not_saved"}, "gui_sync": "not_verified",
                  "client": {"status": "not_stopped"},
                  "verification": {"scope": "client_generated_proxy_graph", "status": "not_requested",
                                   "profile_identity": "catalog_loaded_on_restart"}}
        try:
            self.state.close()
            result["client"]["status"] = "stopping"
            result["status"] = "unknown"
            app.stop(self.state.deadline.remaining())
            result["client"]["status"] = "stopped"
            result["status"] = "partial"
            try:
                generated_path = self.state.store.config_dir / "clash-verge.yaml"
                previous_revision = generated_path.stat().st_mtime_ns if generated_path.exists() else None
                # The exiting GUI saves its old in-memory catalog. Write only after exit.
                self.state.deadline.remaining()
                self.state.store.profiles.activate(entry["uid"])
                if selection:
                    self.state.store.profiles.set_selection(entry["uid"], *selection)
                result["configuration"]["status"] = "saved"
            except OperationError:
                result["configuration"]["status"] = "failed"
                raise
            except (OSError, yaml.YAMLError) as error:
                result["configuration"]["status"] = "failed"
                raise OperationError("PERSISTENCE_FAILED", "Could not save profile after the client exited") from error
            finally:
                # A failed save must not leave networking stopped; relaunch existing configuration.
                app.start()
                result["client"]["status"] = "started"
            app.wait_ready(self.state.deadline)
            result["client"]["status"] = "ready"
            current = self.state.store.profiles.current()
            if not current or current["uid"] != entry["uid"]:
                raise OperationError("STALE_CONTEXT", "Client startup changed the selected profile")
            result["gui_sync"] = "restarted"
            result["reload"]["status"] = "accepted"
            self.state.refresh_runtime(renew_deadline=False)
            # The official client renders its own extensions and DNS/TUN settings.
            while not generated_path.exists() or generated_path.stat().st_mtime_ns == previous_revision:
                time.sleep(min(0.1, self.state.deadline.remaining()))
            generated = self.state.store.read_config("core")
            observed = self._observe(describe_profile(dict(entry, is_current=True), generated), generated,
                                     wait=True, submitted=True, selection=selection)
            observed["verification"].update(scope="client_generated_proxy_graph",
                                             profile_identity="catalog_loaded_on_restart")
            result.update(observed)
            return result
        except OperationError as error:
            observation = error.data or {}
            if observation:
                result["verification"].update(observation.get("verification", {}))
                result["verification"].update(scope="client_generated_proxy_graph",
                                                 profile_identity="catalog_loaded_on_restart")
            error.data = result
            error.needs_reconcile = True
            raise
        except (OSError, yaml.YAMLError) as error:
            raise OperationError("CONFIGURATION_ERROR", "Cannot read client-generated configuration",
                                 data=result, needs_reconcile=True) from error

    def _activate_core(self, identity: str) -> Dict[str, Any]:
        before = self.state.store.profiles.current()
        entry, document = render_profile_config(self.state.store, identity, self.state.deadline)
        result = {"status": "not_applied", "profile_uid": entry["uid"], "name": entry.get("name"),
                  "source": "configured", "reload": {"status": "not_requested", "method": "core_api"},
                  "configuration": {"status": "not_saved"}, "gui_sync": "not_verified",
                  "verification": {"scope": "rendered_proxy_graph", "status": "not_requested",
                                   "profile_identity": "not_exposed"}}
        self._require_association()
        if self.state.store.profiles.current() != before:
            raise OperationError("STALE_CONTEXT", "Profile catalog changed before reload", data=result)
        try:
            self.state.api.load_config(yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
        except ControllerError as error:
            if error.details["request_sent"]:
                result.update(status="unknown")
                result["reload"]["status"] = "unknown"
                raise OperationError("OUTCOME_UNKNOWN", "Core reload response was lost; read runtime before retrying",
                                     data=result, needs_reconcile=True) from None
            result["reload"]["status"] = "rejected" if error.status is not None else "not_sent"
            error.data = result
            raise
        result["reload"]["status"] = "accepted"
        result["status"] = "partial"
        try:
            if self.state.store.profiles.current() != before:
                raise OperationError("STALE_CONTEXT", "Profile catalog changed during reload")
            write_mapping(self.state.store.config_dir / "clash-verge.yaml", document)
            self.state.store.profiles.activate(entry["uid"])
        except OperationError as error:
            result["configuration"]["status"] = "failed"
            error.data = result
            error.needs_reconcile = True
            raise
        except (OSError, yaml.YAMLError) as error:
            result["configuration"]["status"] = "failed"
            raise OperationError("PERSISTENCE_FAILED", "Core accepted the profile but configuration could not be saved",
                                 data=result, needs_reconcile=True) from error
        result["configuration"]["status"] = "saved"
        self.state.refresh_runtime(renew_deadline=False)
        entry = dict(entry, is_current=True)
        try:
            observed = self._observe(describe_profile(entry, document), document, wait=True, submitted=True)
        except OperationError as error:
            error.data = dict(result, **(error.data or {}))
            error.data["status"] = "partial"
            raise
        result.update(observed)
        return result

    def verify(self, identity: str, *, wait: bool = False) -> Dict[str, Any]:
        entry, document = render_profile_config(self.state.store, identity, self.state.deadline)
        return self._observe(describe_profile(entry, document), document, wait=wait)

    def _observe(self, view: Dict[str, Any], document: Dict[str, Any], *, wait: bool,
                 submitted: bool = False, selection: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
        result = {"status": "unconfirmed", "profile_uid": view["profile_uid"], "name": view["name"],
                  "source": "configured", "verification": {"scope": "rendered_proxy_graph",
                  "profile_identity": "not_exposed", "status": "inconclusive"}}
        verification = result["verification"]
        if not view["is_current"] and not wait:
            verification["reason"] = "profile_not_current"
            self._unconfirmed(result)
        if not submitted and not (view["items"] or view["groups"] or view["providers"]):
            verification["reason"] = "dynamic_or_empty_graph"
            self._unconfirmed(result)
        observed_current = view["is_current"]
        while True:
            try:
                remaining = self.state.deadline.remaining()
            except OperationError:
                self._unconfirmed(result)
            current = self.state.store.profiles.current()
            if not current or current["uid"] != view["profile_uid"]:
                if observed_current:
                    raise OperationError("STALE_CONTEXT", "Current profile changed during verification",
                                         data=result, needs_reconcile=True)
                verification.update(status="different", reason="profile_not_current")
                time.sleep(min(0.1, remaining))
                continue
            observed_current = True
            try:
                self._require_association()
                snapshot = self.state.proxy.snapshot()
                providers_match = not view["providers"] or (
                    {item["name"] for item in view["providers"]} <= self.state.api.provider_names())
            except OperationError as exc:
                if exc.code not in ("CONTROLLER_UNAVAILABLE", "DEADLINE_EXCEEDED"):
                    verification.update(status="unavailable", reason=exc.code)
                    raise OperationError(exc.code, str(exc), data=result, needs_reconcile=True) from None
                verification.update(status="unavailable", reason=exc.code)
                if wait:
                    # Startup can replace the generated controller address or service socket.
                    self.state.refresh_runtime(renew_deadline=False)
            else:
                current = self.state.store.profiles.current()
                if not current or current["uid"] != view["profile_uid"]:
                    raise OperationError("STALE_CONTEXT", "Current profile changed during verification",
                                         data=result, needs_reconcile=True)
                nodes_match = all(node["name"] in snapshot.nodes
                                  and _kind(snapshot.nodes[node["name"]]["type"]) == _kind(node["type"])
                                  for node in view["items"])
                groups_match = all(group["name"] in snapshot.groups
                                   and _kind(snapshot.groups[group["name"]].kind) == _kind(group["type"])
                                   and (set(group["proxies"]) <= set(snapshot.groups[group["name"]].choices)
                                        if group["dynamic"] else
                                        snapshot.groups[group["name"]].choices == group["proxies"])
                                   for group in view["groups"])
                builtins = {"GLOBAL", "DIRECT", "REJECT", "REJECT-DROP", "PASS", "PASS-RULE", "COMPATIBLE"}
                names_match = not view["complete"] or (
                    set(snapshot.nodes) - builtins ==
                    {item["name"] for item in view["items"] + view["groups"]} - builtins)
                mode_matches = "mode" not in document or document["mode"] == snapshot.mode
                selection_matches = not selection or (
                    selection[0] in snapshot.groups and snapshot.groups[selection[0]].selected == selection[1])
                if all((nodes_match, groups_match, names_match, providers_match, mode_matches, selection_matches)):
                    verification.update(status="matched")
                    verification.pop("reason", None)
                    result.update(status="verified", source="live")
                    return result
                verification.update(status="different", reason="declared_graph_not_observed" if selection_matches
                                    else "saved_selection_not_observed")
            if not wait:
                self._unconfirmed(result)
            try:
                remaining = self.state.deadline.remaining()
            except OperationError:
                self._unconfirmed(result)
            time.sleep(min(0.1, remaining))

    def _require_association(self) -> None:
        if not self.state.endpoint.profile_bound:
            raise OperationError("UNSUPPORTED_OPERATION", "Controller is not associated with these Verge profiles")

    @staticmethod
    def _unconfirmed(result: Dict[str, Any]) -> None:
        if result["verification"]["status"] == "different":
            result["status"] = "pending"
        raise OperationError("PROFILE_UNCONFIRMED", "Profile runtime graph could not be confirmed",
                             data=result, needs_reconcile=True)


def _kind(value: str) -> str:
    normalized = value.lower().replace("-", "").replace("_", "")
    return {"select": "selector", "ss": "shadowsocks", "ssr": "shadowsocksr"}.get(normalized, normalized)
