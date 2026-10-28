"""Render subscription extensions into a complete, private mihomo configuration."""

import copy
import json
from typing import Any, Dict, Tuple

from clashier.adapters.profiles import describe_profile
from clashier.adapters.verge_store import VergeStore
from clashier.adapters.yaml_files import read_mapping
from clashier.errors import OperationError
from clashier.models import Deadline

# These settings belong to the running host, rather than an individual subscription.
HOST_KEYS = (
    "external-controller", "external-controller-tls", "external-controller-unix", "external-controller-pipe",
    "external-controller-cors", "secret", "mixed-port", "port", "socks-port", "redir-port", "tproxy-port",
    "mode", "allow-lan", "bind-address", "log-level", "ipv6", "unified-delay",
)


def render_profile_config(store: VergeStore, identity: str,
                          deadline: Deadline) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Apply catalog-selected extensions while retaining the current host's control plane."""
    entry, document = store.profiles.document(identity)
    document = _merge({}, document)
    describe_profile(entry, document)
    records = {item["uid"]: item for item in store.profiles.list()}
    options = entry.get("option") or {}
    profile_name = entry.get("name") or ""
    if not isinstance(options, dict):
        raise OperationError("CONFIGURATION_ERROR", "Invalid profile extension options")
    if any(options.get(key) is not None and not isinstance(options[key], str)
           for key in ("rules", "proxies", "groups", "merge", "script")):
        raise OperationError("CONFIGURATION_ERROR", "Profile extension identities must be strings")

    def extension(kind: str, uid: str, *, required: bool = False) -> Any:
        item = records.get(uid)
        if item is None:
            if required:
                raise OperationError("NOT_FOUND", "Selected profile extension is absent from the catalog")
            return None
        if item.get("type") != kind:
            raise OperationError("CONFIGURATION_ERROR", "Profile extension has the wrong type")
        return store.profiles.extension(item)

    for kind, field in (("rules", "rules"), ("proxies", "proxies"), ("groups", "proxy-groups")):
        uid = options.get(kind) or kind.capitalize()
        edits = extension(kind, uid, required=bool(options.get(kind)))
        if edits is not None:
            _edit_sequence(document, field, edits)

    current = store.read_config("core")
    defaults = read_mapping(store.config_dir / "config.yaml")
    document = _merge(document, defaults)
    protected = {key: copy.deepcopy(current[key]) for key in HOST_KEYS if key in current}
    _retain_host(document, current, protected)
    for kind, global_uid in (("merge", "Merge"), ("script", "Script")):
        value = extension(kind, global_uid)
        if value is not None:
            document = _apply_extension(document, kind, value, profile_name, deadline)
    for kind in ("merge", "script"):
        uid = options.get(kind)
        if uid and uid != kind.capitalize():
            value = extension(kind, uid, required=True)
            document = _apply_extension(document, kind, value, profile_name, deadline)

    _retain_host(document, current, protected)
    settings = store.read_config("verge")
    if settings.get("enable_dns_settings"):
        for key in ("dns", "hosts"):
            if key in current:
                document[key] = copy.deepcopy(current[key])
    describe_profile(entry, document)
    if settings.get("enable_builtin_enhanced", True):
        if document.get("mode") == "script":
            document["mode"] = "rule"
        for node in document.get("proxies") or []:
            if isinstance(node.get("alpn"), str):
                node["alpn"] = [node["alpn"]]
    return entry, document


def _retain_host(document: Dict[str, Any], current: Dict[str, Any], protected: Dict[str, Any]) -> None:
    for key in HOST_KEYS:
        document.pop(key, None)
    document.update(copy.deepcopy(protected))
    if "tun" in current:
        document["tun"] = copy.deepcopy(current["tun"])


def _merge(base: Dict[str, Any], overlay: Dict[str, Any], *, root: bool = True) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for raw_key, value in overlay.items():
        if not isinstance(raw_key, str):
            raise OperationError("CONFIGURATION_ERROR", "Profile extension keys must be strings")
        key = raw_key.lower() if root else raw_key
        if isinstance(value, dict) and isinstance(result.get(key), dict) and not (root and key == "hosts"):
            if root and key == "dns":
                result[key].update(copy.deepcopy(value))
            else:
                result[key] = _merge(result[key], value, root=False)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _edit_sequence(document: Dict[str, Any], field: str, edits: Dict[str, Any]) -> None:
    prepend, append, delete = (edits.get(key, []) for key in ("prepend", "append", "delete"))
    if any(not isinstance(value, list) for value in (prepend, append, delete)) or any(
        not isinstance(value, str) for value in delete
    ):
        raise OperationError("CONFIGURATION_ERROR", "Invalid profile sequence extension")
    existing = document.get(field) or []
    if not isinstance(existing, list):
        raise OperationError("CONFIGURATION_ERROR", "Profile sequence must be a list")
    kept = [item for item in existing if (item.get("name") if isinstance(item, dict) else item) not in delete]
    document[field] = copy.deepcopy(prepend + kept + append)
    if field == "proxies":
        added = [item["name"] for item in prepend + append if isinstance(item, dict) and "name" in item]
        inserted = False
        for group in document.get("proxy-groups") or []:
            has_choices = "proxies" in group
            choices = [name for name in group.get("proxies") or [] if name not in delete]
            if added and not inserted and group.get("type", "").lower() in ("select", "selector"):
                choices = list(dict.fromkeys(added + choices))
                inserted = True
                has_choices = True
            if has_choices:
                group["proxies"] = choices


def _apply_extension(document: Dict[str, Any], kind: str, value: Any, name: str,
                     deadline: Deadline) -> Dict[str, Any]:
    if kind == "merge":
        return _merge(document, value)
    if not value.strip():
        return document
    from py_mini_racer import JSEvalException, JSTimeoutException, MiniRacer

    try:
        config_json = json.dumps(document, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError):
        raise OperationError("CONFIGURATION_ERROR", "Profile data cannot be passed to a JavaScript extension") from None
    source = """(() => {
        const console = Object.freeze(Object.fromEntries(
            ['log','info','warn','error','debug','table'].map(name => [name, () => {}])));
    """ + value + """
        const result = main(JSON.parse(""" + json.dumps(config_json) + ")," + json.dumps(name) + """);
        if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.then === 'function') {
            throw new Error('Profile script must return a synchronous configuration object');
        }
        return JSON.stringify(result);
    })()"""
    context = MiniRacer()
    try:
        result = json.loads(context.eval(source, timeout_sec=deadline.remaining()))
    except JSTimeoutException:
        raise OperationError("DEADLINE_EXCEEDED", "Profile JavaScript extension timed out") from None
    except (JSEvalException, ValueError, TypeError):
        # Script messages and console output can contain subscription credentials.
        raise OperationError("SCRIPT_FAILED", "Profile JavaScript extension failed") from None
    finally:
        context.close()
    if not isinstance(result, dict):
        raise OperationError("SCRIPT_FAILED", "Profile JavaScript extension did not return an object")
    return {key.lower(): value for key, value in result.items()}
