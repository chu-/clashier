"""Host settings and application lifecycle commands."""

from typing import Optional

import click

from clashier import platforms
from clashier.bootstrap import Bootstrap
from clashier.cli.render import emit

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def host() -> None:
    """Configure host proxy settings and control the Verge application."""


@host.group("proxy")
def system_proxy() -> None:
    """Read or set the configured system proxy switch."""


@system_proxy.command("get")
@pass_state
def proxy_get(state: Bootstrap) -> None:
    """Read the configured system proxy switch and guard."""
    settings = state.store.read_config("verge")
    emit({"enabled": settings.get("enable_system_proxy", False),
          "guard": settings.get("enable_proxy_guard", False)}, state, source="configured")


@system_proxy.command("set")
@click.argument("value", type=click.Choice(["on", "off"]))
@pass_state
def proxy_set(state: Bootstrap, value: str) -> None:
    """Set on/off explicitly; application reload is pending."""
    state.store.update_settings({"enable_system_proxy": value == "on"})
    emit({"status": "pending", "enabled": value == "on"}, state, source="configured")


@host.group("tun")
def tun() -> None:
    """Read or set configured TUN mode."""


@tun.command("get")
@pass_state
def tun_get(state: Bootstrap) -> None:
    """Read configured TUN mode."""
    emit({"enabled": state.store.read_config("verge").get("enable_tun_mode", False)}, state, source="configured")


@tun.command("set")
@click.argument("value", type=click.Choice(["on", "off"]))
@pass_state
def tun_set(state: Bootstrap, value: str) -> None:
    """Set TUN on/off explicitly; application reload is pending."""
    state.store.update_settings({"enable_tun_mode": value == "on"})
    emit({"status": "pending", "enabled": value == "on"}, state, source="configured")


@host.group("ports")
def ports() -> None:
    """Read or set configured listener ports."""


@ports.command("get")
@pass_state
def ports_get(state: Bootstrap) -> None:
    """Read configured listener ports."""
    emit(state.store.configured_ports(), state, source="configured")


@ports.command("set")
@click.argument("kind", type=click.Choice(["http", "socks", "mixed", "redir"]))
@click.argument("port", type=click.IntRange(1, 65535))
@click.option("--enable/--disable", default=None)
@pass_state
def ports_set(state: Bootstrap, kind: str, port: int, enable: Optional[bool]) -> None:
    """Set one port and optional listener switch."""
    settings = state.store.configure_port(kind, port, enable)
    emit({"status": "pending", "ports": settings}, state, source="configured")


@host.command()
@pass_state
def restart(state: Bootstrap) -> None:
    """Restart the GUI application after resolving its executable."""
    state.renew_deadline(state.timeout if state.explicit_timeout else 30.0)
    platforms.restart_verge(state.deadline.remaining())
    emit({"status": "started"}, state)


@host.command("open")
@click.argument("target", type=click.Choice(["config", "logs"]))
@pass_state
def open_directory(state: Bootstrap, target: str) -> None:
    """Open a configuration or log directory in the host file manager."""
    path = state.store.config_dir if target == "config" else state.store.logs_dir
    platforms.open_directory(path)
    emit({"status": "opened", "path": str(path)}, state)


@host.command()
@pass_state
def webui(state: Bootstrap) -> None:
    """List configured web interfaces."""
    emit({"items": state.store.read_config("verge").get("web_ui_list") or []}, state, source="configured")
