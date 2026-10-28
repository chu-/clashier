"""Locate Verge resources and perform explicit host operations."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from clashier.errors import OperationError
from clashier.models import Deadline

VERGE_APP_ID = "io.github.clash-verge-rev.clash-verge-rev"


def platform_name(value: Optional[str] = None) -> str:
    """Normalize supported system names and reject unimplemented platforms."""
    value = (value or sys.platform).lower()
    for prefix, name in (("darwin", "macos"), ("macos", "macos"), ("win", "windows"),
                         ("cygwin", "windows"), ("linux", "linux")):
        if value.startswith(prefix):
            return name
    raise OperationError("UNSUPPORTED_OPERATION", "Unsupported platform: {}".format(value))


def config_locations(platform: Optional[str] = None, environ: Optional[Dict[str, str]] = None,
                     home: Optional[Path] = None) -> List[Path]:
    """Return the controlled application's config locations in discovery order."""
    system = platform_name(platform)
    env = os.environ if environ is None else environ
    user_dir = Path.home() if home is None else home
    if system == "macos":
        return [user_dir / "Library/Application Support" / VERGE_APP_ID]
    if system == "linux":
        data = Path(env.get("XDG_DATA_HOME") or user_dir / ".local/share")
        config = Path(env.get("XDG_CONFIG_HOME") or user_dir / ".config")
        return [data / VERGE_APP_ID, config / VERGE_APP_ID, config / "clash-verge"]
    roaming = Path(env.get("APPDATA") or user_dir / "AppData/Roaming")
    local = Path(env.get("LOCALAPPDATA") or user_dir / "AppData/Local")
    return [roaming / VERGE_APP_ID, roaming / "clash-verge-rev",
            local / VERGE_APP_ID, local / "clash-verge-rev",
            Path("C:/Program Files/Clash Verge"), Path("C:/Program Files (x86)/Clash Verge")]


def locate_config_dir(explicit: Optional[str] = None, platform: Optional[str] = None,
                      environ: Optional[Dict[str, str]] = None, home: Optional[Path] = None) -> Path:
    """Resolve explicit path, environment override, existing location, then default."""
    env = os.environ if environ is None else environ
    override = explicit or env.get("CLASH_VERGE_DIR")
    if override:
        return Path(override).expanduser()
    locations = config_locations(platform, env, home)
    return next((location for location in locations if location.is_dir()), locations[0])


def controller_sockets() -> List[Path]:
    """Discover the current macOS user's existing service socket."""
    if platform_name() == "macos":
        socket_path = Path("/var/run/clash-verge-service/users/{}/verge-mihomo.sock".format(os.getuid()))
        if socket_path.exists():
            return [socket_path]
    return []


def find_verge_executable(platform: Optional[str] = None,
                          environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Find an installed GUI executable, excluding directories and non-executable files."""
    system = platform_name(platform)
    env = os.environ if environ is None else environ
    if system == "macos":
        candidates = [root / "Clash Verge.app/Contents/MacOS/clash-verge"
                      for root in (Path("/Applications"), Path.home() / "Applications")]
    elif system == "windows":
        local = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        candidates = [local / "Programs/Clash Verge/clash-verge.exe"]
        candidates.extend(Path(env.get(variable) or default) / "Clash Verge/clash-verge.exe"
                          for variable, default in (("ProgramFiles", "C:/Program Files"),
                                                    ("ProgramFiles(x86)", "C:/Program Files (x86)")))
    else:
        found = shutil.which("clash-verge", path=env.get("PATH"))
        candidates = [Path(found)] if found else [Path("/usr/bin/clash-verge")]
    return next((str(candidate) for candidate in candidates
                 if candidate.is_file() and (system == "windows" or os.access(candidate, os.X_OK))), None)


def _run_host_command(arguments: List[str], timeout: float) -> int:
    try:
        return subprocess.run(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout, check=False).returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OperationError("HOST_COMMAND_FAILED", "{} failed ({})".format(
            arguments[0], type(error).__name__)) from None


def open_directory(directory: Path) -> None:
    """Ask the platform file manager to open a directory and check dispatch success."""
    system = platform_name()
    if system == "windows":
        os.startfile(str(directory))  # type: ignore[attr-defined]  # noqa: S606
        return
    command = "open" if system == "macos" else "xdg-open"
    if _run_host_command([command, str(directory)], 5.0) != 0:
        raise OperationError("HOST_COMMAND_FAILED", "File manager could not open the directory")


class VergeApp:
    """Stop the official client before editing its catalog, then await client readiness."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.executable = find_verge_executable()
        if self.executable is None:
            raise OperationError("NOT_FOUND", "Clash Verge app not found")
        self.config_dir = config_dir
        if config_dir is not None and config_dir.resolve() not in {
            location.resolve() for location in config_locations()
        }:
            raise OperationError("UNSUPPORTED_OPERATION", "Client restart requires its native configuration directory; "
                                 "use --core-only for another configuration directory")

    def stop(self, timeout: float) -> None:
        """Wait for graceful Unix shutdown; never escalate to killing the core or service."""
        budget = Deadline(timeout)
        image = Path(self.executable).name
        windows = platform_name() == "windows"
        owner = [] if windows else ["-u", str(os.getuid())]
        stop = ["taskkill", "/F", "/IM", image] if windows else ["pkill", "-TERM", *owner, "-x", image]
        stopped = _run_host_command(stop, budget.remaining())
        absent = 128 if windows else 1
        if stopped not in (0, absent):
            raise OperationError("HOST_COMMAND_FAILED", "Could not stop the Clash Verge process")
        if not windows and stopped == 0:
            while True:
                running = _run_host_command(["pgrep", *owner, "-x", image], budget.remaining())
                if running == 1:
                    break
                if running != 0:
                    raise OperationError("HOST_COMMAND_FAILED", "Could not observe the Clash Verge process")
                time.sleep(min(0.05, budget.remaining()))

    def start(self) -> None:
        """Launch independently so client logs and inherited pipes do not corrupt CLI output."""
        if platform_name() == "macos":
            running = _run_host_command(["pgrep", "-u", str(os.getuid()), "-x", Path(self.executable).name], 5.0)
            if running == 0:
                return
            if running != 1:
                raise OperationError("HOST_COMMAND_FAILED", "Could not check the Clash Verge process")
        try:
            subprocess.Popen([self.executable], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise OperationError("HOST_COMMAND_FAILED", "Could not start Clash Verge") from None

    def wait_ready(self, deadline: Deadline) -> None:
        """Read PAC availability, which the native client enables once its core is running."""
        record_path = self.config_dir / "singleton-instance.json"
        with httpx.Client(trust_env=False) as client:
            while True:
                if record_path.exists():
                    try:
                        record = json.loads(record_path.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        raise OperationError("CONFIGURATION_ERROR", "Cannot read the client instance record") from None
                    if not isinstance(record, dict) or type(record.get("port")) is not int or not (
                        1 <= record["port"] <= 65535
                    ):
                        raise OperationError("CONFIGURATION_ERROR", "Invalid client instance record")
                    try:
                        # /commands/visible can create a second window during startup.
                        response = client.get("http://127.0.0.1:{}/commands/pac".format(record["port"]),
                                              timeout=deadline.remaining())
                    except (httpx.ConnectError, httpx.TimeoutException):
                        pass
                    else:
                        if response.status_code == 200:
                            return
                        if response.status_code not in (404, 503):
                            raise OperationError("HOST_COMMAND_FAILED", "Client readiness request failed")
                time.sleep(min(0.1, deadline.remaining()))


def restart_verge(timeout: float = 30.0) -> None:
    """Restart the installed client, waiting for its old process to exit first."""
    app = VergeApp()
    app.stop(timeout)
    app.start()
