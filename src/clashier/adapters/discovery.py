"""Find controller endpoints without silently switching explicit targets."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from clashier import platforms
from clashier.adapters.mihomo import Mihomo
from clashier.adapters.transport import DEFAULT_CONTROLLER, normalize_controller
from clashier.adapters.verge_store import VergeStore
from clashier.errors import OperationError
from clashier.models import Deadline, Endpoint


def candidates(store: VergeStore, explicit: Optional[str] = None,
               secret: Optional[str] = None) -> List[Endpoint]:
    """Collect addresses from config and the current user's service runtime."""
    config = store.read_config("core")
    configured_secret = config.get("secret")
    if configured_secret is None:
        configured_secret = (store.read_config("verge").get("clash_info") or {}).get("secret")
    configured_secret = configured_secret if secret is None else secret
    result = []
    for key, scheme in (("external-controller", ""), ("external-controller-tls", "https://"),
                        ("external-controller-unix", "unix://")):
        value = config.get(key)
        if not value:
            continue
        if scheme == "unix://" and not Path(value).is_absolute():
            value = str(store.config_dir / value)
        address = normalize_controller(scheme + value if scheme and not value.startswith(scheme) else value)
        result.append(Endpoint(address, "config", True, configured_secret))
    for path in platforms.controller_sockets():
        bound = store.config_dir.resolve() == platforms.locate_config_dir().resolve()
        result.append(Endpoint(normalize_controller("unix://" + str(path)), "service", bound, configured_secret))
    result = list({item.address: item for item in result}.values())
    if explicit:
        address = normalize_controller(explicit)
        bound = any(item.address == address and item.profile_bound for item in result)
        return [Endpoint(address, "explicit", bound, configured_secret)]
    if not result:
        if config.get("external-controller-pipe"):
            raise OperationError("UNSUPPORTED_OPERATION", "Windows named pipe controllers are not implemented")
        result.append(Endpoint(normalize_controller(DEFAULT_CONTROLLER), "default-port", False, configured_secret))
    return result


def discover(endpoints: List[Endpoint], deadline: Deadline) -> Tuple[List[Endpoint], List[Dict[str, Any]]]:
    """Probe candidates within one budget and keep useful failure diagnostics."""
    reachable = []
    failures = []
    for index, endpoint in enumerate(endpoints):
        api = None
        try:
            timeout = deadline.remaining() / (len(endpoints) - index)
            api = Mihomo(endpoint.address, endpoint.secret, timeout=timeout, deadline=deadline)
            version, config = api.version(), api.configs()
            if not isinstance(version.get("version"), str) or not isinstance(config.get("mode"), str):
                raise OperationError("INVALID_RESPONSE", "Endpoint is not a compatible mihomo controller")
            reachable.append(endpoint)
        except OperationError as exc:
            failures.append({"instance_id": endpoint.instance_id, "source": endpoint.source,
                             "code": exc.code, "message": str(exc)})
        finally:
            if api:
                api.close()
    return reachable, failures


def resolve(endpoints: List[Endpoint], deadline: Deadline, instance: Optional[str] = None) -> Endpoint:
    """Choose a single controller; a specified instance never changes implicitly."""
    if instance:
        endpoints = [item for item in endpoints if item.instance_id == instance]
        if not endpoints:
            raise OperationError("NOT_FOUND", "Controller instance not found")
    if len(endpoints) == 1:
        return endpoints[0]
    reachable, failures = discover(endpoints, deadline)
    if not reachable:
        raise OperationError("CONTROLLER_UNAVAILABLE", "No reachable Clash controller",
                             details={"candidates": failures}, safe_to_retry=True)
    if len(reachable) > 1:
        raise OperationError("AMBIGUOUS_TARGET", "Multiple controllers found; specify --instance",
                             details={"instances": [item.instance_id for item in reachable]})
    return reachable[0]
