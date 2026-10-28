"""Explicit configuration inspection and file updates."""

import re
from typing import Optional

import click

from clashier.bootstrap import Bootstrap
from clashier.cli.render import emit
from clashier.errors import OperationError

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def config() -> None:
    """Inspect or update configured values; reads do not imply live state."""


@config.command("get")
@click.argument("target", type=click.Choice(["core", "verge"]))
@pass_state
def get_config(state: Bootstrap, target: str) -> None:
    """Export raw configuration, which may contain credentials."""
    values = state.store.read_config(target)
    emit({"config": values}, state, source="configured")


@config.command("set")
@click.argument("key")
@click.argument("value")
@pass_state
def set_config(state: Bootstrap, key: str, value: str) -> None:
    if value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    else:
        parsed = int(value) if re.fullmatch(r"-?\d+", value) else value
    state.store.update_settings({key: parsed})
    emit({"status": "pending", "key": key, "value": parsed}, state, source="configured")


@config.command()
@pass_state
def dns(state: Bootstrap) -> None:
    emit({"dns": state.store.read_config("core").get("dns") or {}}, state, source="configured")


@config.command()
@click.option("--type", "rule_type", default=None)
@click.option("--limit", default=20, type=click.IntRange(min=0))
@pass_state
def rules(state: Bootstrap, rule_type: Optional[str], limit: int) -> None:
    items = state.store.routing_rules()
    if rule_type is not None:
        items = [rule for rule in items if rule["type"] == rule_type]
    emit({"items": items[:limit]}, state, source="configured")


@config.command()
@pass_state
def path(state: Bootstrap) -> None:
    emit({"path": str(state.store.config_dir), "exists": state.store.config_dir.is_dir()}, state, source="configured")


@config.command()
@pass_state
def refresh(state: Bootstrap) -> None:
    """Notify a config watcher without claiming that the core reloaded."""
    target = state.store.profiles.path
    if not target.exists():
        raise OperationError("NOT_FOUND", "profiles.yaml not found")
    target.touch()
    emit({"status": "pending"}, state, source="configured")
