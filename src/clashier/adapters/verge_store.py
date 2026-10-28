"""Configured documents, listener settings, snapshots and bounded log reads."""

import re
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from clashier.adapters.profiles import ProfileStore
from clashier.adapters.yaml_files import read_mapping, write_mapping
from clashier.errors import OperationError

CONFIG_FILES = {"core": "clash-verge.yaml", "verge": "verge.yaml"}
SNAPSHOT_FILES = ("profiles.yaml", "verge.yaml", "clash-verge.yaml")
LISTENERS = {
    "http": ("verge_port", "verge_http_enabled"),
    "socks": ("verge_socks_port", "verge_socks_enabled"),
    "mixed": ("verge_mixed_port", None),
    "redir": ("verge_redir_port", "verge_redir_enabled"),
}


class VergeStore:
    """Access the configured resources of a single Verge installation."""

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.profiles = ProfileStore(self.config_dir)
        self.logs_dir = self.config_dir / "logs"
        self.backups_dir = self.config_dir / "clash-verge-rev-backup"

    def read_config(self, target: str) -> Dict[str, Any]:
        """Read the configured core or GUI document without creating directories."""
        return read_mapping(self.config_dir / CONFIG_FILES[target])

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Merge GUI settings once and return the document that was saved."""
        settings = self.read_config("verge")
        if all(key in settings and settings[key] == value for key, value in changes.items()):
            return settings
        settings.update(changes)
        write_mapping(self.config_dir / CONFIG_FILES["verge"], settings)
        return settings

    @staticmethod
    def _port_view(settings: Dict[str, Any]) -> Dict[str, Any]:
        ports = {kind + "_port": settings.get(keys[0]) for kind, keys in LISTENERS.items()}
        ports.update({"enable_" + kind: settings.get(keys[1])
                      for kind, keys in LISTENERS.items() if keys[1] is not None})
        return ports

    def configured_ports(self) -> Dict[str, Any]:
        """Project configured listener values into the command's result fields."""
        return self._port_view(self.read_config("verge"))

    def configure_port(self, kind: str, port: int, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Save one listener's port and optional switch without a second file read."""
        port_key, switch_key = LISTENERS[kind]
        changes = {port_key: port}
        if switch_key is not None and enabled is not None:
            changes[switch_key] = enabled
        return self._port_view(self.update_settings(changes))

    def routing_rules(self) -> List[Dict[str, str]]:
        """Parse configured routing rules into their type, value and payload fields."""
        rules = self.read_config("core").get("rules") or []
        if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
            raise OperationError("CONFIGURATION_ERROR", "Expected rule strings in clash-verge.yaml")
        result = []
        for rule in rules:
            kind, _, remainder = rule.partition(",")
            value, _, payload = remainder.partition(",")
            result.append({"type": kind.strip(), "value": value.strip(), "payload": payload.strip()})
        return result

    def _snapshot_path(self, name: str) -> Path:
        if name in ("", ".", "..") or name.endswith((".", " ")) or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
            raise ValueError("Backup name must be a single valid directory name")
        return self.backups_dir / name

    def create_backup(self, name: Optional[str] = None) -> str:
        """Copy existing configuration files to a new, non-overwriting snapshot."""
        destination = self._snapshot_path(name if name is not None else datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        sources = [self.config_dir / name for name in SNAPSHOT_FILES if (self.config_dir / name).is_file()]
        if not sources:
            raise OperationError("NOT_FOUND", "No configuration files to back up")
        if destination.exists():
            raise OperationError("ALREADY_EXISTS", "Backup already exists: {}".format(destination.name))
        destination.mkdir(parents=True)
        for source in sources:
            shutil.copy2(source, destination / source.name)
        return str(destination)

    def list_backups(self) -> List[Dict[str, str]]:
        """List configuration snapshots, newest first."""
        folders = [folder for folder in self.backups_dir.glob("*") if folder.is_dir()]
        folders.sort(key=lambda folder: folder.stat().st_mtime, reverse=True)
        return [{"name": folder.name, "path": str(folder),
                 "created": datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
                for folder in folders]

    def restore_backup(self, name: str) -> None:
        """Restore known files from an existing snapshot; reload remains pending."""
        snapshot = self._snapshot_path(name)
        if not snapshot.is_dir():
            raise OperationError("NOT_FOUND", "Backup not found: {}".format(name))
        for filename in SNAPSHOT_FILES:
            source = snapshot / filename
            if source.is_file():
                shutil.copy2(source, self.config_dir / filename)

    def tail_logs(self, limit: int) -> List[str]:
        """Read at most the last limit lines from the newest log using bounded memory."""
        if limit <= 0:
            return []
        newest = max((path for path in self.logs_dir.glob("*.log") if path.is_file()),
                     key=lambda path: path.stat().st_mtime, default=None)
        if newest is None:
            return []
        with newest.open(encoding="utf-8", errors="replace") as stream:
            return list(deque(stream, maxlen=limit))
