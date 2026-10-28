"""Configuration backup commands."""

from typing import Optional

import click

from clashier.bootstrap import Bootstrap
from clashier.cli.render import emit

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def backup() -> None:
    """Create, list and restore configuration backups."""


@backup.command("list")
@pass_state
def list_backups(state: Bootstrap) -> None:
    emit({"items": state.store.list_backups()}, state, source="configured")


@backup.command()
@click.argument("name", required=False)
@pass_state
def create(state: Bootstrap, name: Optional[str]) -> None:
    try:
        path = state.store.create_backup(name)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    emit({"status": "saved", "path": path}, state, source="configured")


@backup.command()
@click.argument("name")
@pass_state
def restore(state: Bootstrap, name: str) -> None:
    try:
        state.store.restore_backup(name)
    except ValueError as error:
        raise click.UsageError(str(error)) from None
    emit({"status": "pending", "name": name}, state, source="configured")
