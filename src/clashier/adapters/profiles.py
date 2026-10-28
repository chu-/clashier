"""Verge profile catalog operations and subscription content storage."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from clashier.adapters.yaml_files import read_mapping, write_mapping, write_text
from clashier.errors import OperationError


class ProfileStore:
    """Operate on a profile catalog while retaining unrecognized GUI fields."""

    def __init__(self, config_dir: Path):
        self.path = config_dir / "profiles.yaml"
        self.directory = config_dir / "profiles"

    def _read_catalog(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        catalog = read_mapping(self.path)
        entries = catalog.get("items")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise OperationError("CONFIGURATION_ERROR", "Expected a profile list in profiles.yaml")
        identities = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("uid"), str) or not entry["uid"]:
                raise OperationError("CONFIGURATION_ERROR", "Expected a profile uid in profiles.yaml")
            if entry["uid"] in identities:
                raise OperationError("CONFIGURATION_ERROR", "Duplicate profile uid in profiles.yaml")
            identities.add(entry["uid"])
            selections = entry.get("selected")
            if selections is not None and (
                not isinstance(selections, list) or any(
                    not isinstance(row, dict) or not isinstance(row.get("name"), str)
                    or not isinstance(row.get("now"), str) for row in selections
                )
            ):
                raise OperationError("CONFIGURATION_ERROR", "Invalid profile selections in profiles.yaml")
        return catalog, entries

    def list(self) -> List[Dict[str, Any]]:
        """Return profile records with the active marker projected from the catalog."""
        catalog, entries = self._read_catalog()
        return [dict(entry, is_current=entry["uid"] == catalog.get("current")) for entry in entries]

    def current(self) -> Optional[Dict[str, Any]]:
        """Return the catalog's active record, if one is present."""
        return next((entry for entry in self.list() if entry["is_current"]), None)

    def find(self, identity: str) -> Optional[Dict[str, Any]]:
        """Resolve an exact uid first, otherwise require an unambiguous display name."""
        entries = self.list()
        by_uid = next((entry for entry in entries if entry["uid"] == identity), None)
        if by_uid is not None:
            return by_uid
        matches = [entry for entry in entries if entry.get("name") == identity]
        if len(matches) > 1:
            raise OperationError("AMBIGUOUS_TARGET", "Profile name is ambiguous; use an exact uid")
        return matches[0] if matches else None

    def document(self, identity: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Read a selectable profile and its private configuration for internal operations."""
        entry = self.find(identity)
        if entry is None:
            raise OperationError("NOT_FOUND", "Profile not found")
        if entry.get("type") not in ("remote", "local", "url"):
            raise OperationError("UNSUPPORTED_OPERATION", "Only subscription and local profiles have proxy graphs")
        path = self._content_path(entry)
        if not path.is_file():
            raise OperationError("NOT_FOUND", "Profile content file not found")
        return entry, read_mapping(path)

    def inspect(self, identity: str) -> Dict[str, Any]:
        """Read a profile's declared graph without exporting credentials or fetching providers."""
        entry, document = self.document(identity)
        return describe_profile(entry, document)

    def extension(self, entry: Dict[str, Any]) -> Any:
        """Read one catalog-selected extension in its native YAML or JavaScript representation."""
        path = self._content_path(entry)
        if not path.is_file():
            raise OperationError("NOT_FOUND", "Profile extension content file not found")
        return path.read_text(encoding="utf-8") if entry["type"] == "script" else read_mapping(path)

    def activate(self, uid: str) -> None:
        """Set the catalog's current profile without rewriting unrelated application settings."""
        catalog, entries = self._read_catalog()
        if not any(entry["uid"] == uid for entry in entries):
            raise OperationError("NOT_FOUND", "Profile uid not found")
        catalog["current"] = uid
        write_mapping(self.path, catalog)

    def import_subscription(self, url: str, contents: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Save downloaded content under a generated identity and register its metadata."""
        catalog, entries = self._read_catalog()
        uid = "clashier-" + uuid.uuid4().hex
        entry = {"uid": uid, "name": name or datetime.now().strftime("profile_%Y%m%d%H%M%S"),
                 "type": "url", "url": url, "file": uid + ".yaml"}
        write_text(self.directory / entry["file"], contents)
        catalog["items"] = entries + [entry]
        write_mapping(self.path, catalog)
        return entry

    def _content_path(self, entry: Dict[str, Any]) -> Path:
        filename = entry.get("file") or entry["uid"] + ".yaml"
        if not isinstance(filename, str) or filename in (".", "..") or "\\" in filename:
            raise OperationError("CONFIGURATION_ERROR", "Invalid profile file in profiles.yaml")
        if Path(filename).name != filename:
            raise OperationError("CONFIGURATION_ERROR", "Profile file must be a single filename")
        return self.directory / filename

    def delete(self, uid: str) -> None:
        """Remove an inactive record and its content file."""
        catalog, entries = self._read_catalog()
        target = next((entry for entry in entries if entry["uid"] == uid), None)
        if target is None:
            raise OperationError("NOT_FOUND", "Profile uid not found")
        if uid == catalog.get("current"):
            raise OperationError("PRECONDITION_FAILED", "Cannot delete active profile")
        content = self._content_path(target)
        catalog["items"] = [entry for entry in entries if entry["uid"] != uid]
        write_mapping(self.path, catalog)
        content.unlink(missing_ok=True)

    def set_selection(self, expected_uid: str, group: str, node: str) -> bool:
        """Update one group's memory only while the expected profile is current."""
        catalog, entries = self._read_catalog()
        if catalog.get("current") != expected_uid:
            raise OperationError("STALE_CONTEXT", "Current profile changed before persistence")
        target = next((entry for entry in entries if entry["uid"] == expected_uid), None)
        if target is None:
            raise OperationError("STALE_CONTEXT", "Current profile is absent from the catalog")
        rows = target.get("selected") or []
        selection = next((row for row in rows if row["name"] == group), None)
        if selection is not None and selection["now"] == node:
            return False
        if selection is None:
            rows.append({"name": group, "now": node})
        else:
            selection["now"] = node
        target["selected"] = rows
        write_mapping(self.path, catalog)
        return True

    def subscription_usage(self) -> Optional[Dict[str, Any]]:
        """Return the current subscription's recorded byte and GiB counters."""
        profile = self.current()
        if profile is None:
            return None
        extra = profile.get("extra") or {}
        counters = {name: int(extra.get(name) or 0) for name in ("upload", "download", "total")}
        return dict(counters, **{name + "_gb": round(value / (1024 ** 3), 2)
                                for name, value in counters.items()})


def describe_profile(entry: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and project a profile graph, excluding connection credentials."""
    nodes = _named_entries(document.get("proxies"), "proxies")
    groups = _named_entries(document.get("proxy-groups"), "proxy-groups")
    if {item["name"] for item in nodes} & {item["name"] for item in groups}:
        raise OperationError("CONFIGURATION_ERROR", "Proxy and group names must be distinct")
    providers = document.get("proxy-providers")
    if providers is None:
        providers = {}
    if not isinstance(providers, dict) or any(
        not isinstance(name, str) or not isinstance(value, dict) for name, value in providers.items()
    ):
        raise OperationError("CONFIGURATION_ERROR", "Invalid proxy-providers in profile")
    projected_groups = []
    for group in groups:
        choices = group.get("proxies") if group.get("proxies") is not None else []
        sources = group.get("use") if group.get("use") is not None else []
        if any(not isinstance(values, list) or any(not isinstance(value, str) for value in values)
               for values in (choices, sources)):
            raise OperationError("CONFIGURATION_ERROR", "Invalid proxy group choices in profile")
        dynamic = bool(sources) or any(group.get(key) for key in (
            "include-all", "include-all-proxies", "include-all-providers", "filter", "exclude-filter",
            "exclude-type"))
        projected_groups.append({"name": group["name"], "type": group["type"],
                                 "proxies": choices, "use": sources, "dynamic": dynamic})
    return {"profile_uid": entry["uid"], "name": entry.get("name"), "is_current": entry["is_current"],
            "source": "configured", "view": "declared", "groups": projected_groups,
            "items": [{"name": node["name"], "type": node["type"]} for node in nodes],
            "providers": [{"name": name} for name in providers],
            "complete": not providers and not any(group["dynamic"] for group in projected_groups)}


def _named_entries(value: Any, field: str) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]
        or not isinstance(item.get("type"), str) for item in value
    ):
        raise OperationError("CONFIGURATION_ERROR", "Invalid {} in profile".format(field))
    if len({item["name"] for item in value}) != len(value):
        raise OperationError("CONFIGURATION_ERROR", "Duplicate names in profile {}".format(field))
    return value
