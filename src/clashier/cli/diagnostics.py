"""Log queries and explicit URL health measurements."""

from typing import Optional

import click

from clashier.adapters.web import check_url
from clashier.bootstrap import Bootstrap
from clashier.cli.protocol import HTTP_URL
from clashier.cli.render import emit

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def logs() -> None:
    """Read or search configured log files."""


@logs.command()
@click.option("--lines", default=50, type=click.IntRange(min=1))
@pass_state
def read(state: Bootstrap, lines: int) -> None:
    emit({"items": [line.rstrip("\r\n") for line in state.store.tail_logs(lines)]}, state, source="configured")


@logs.command()
@click.argument("keyword")
@click.option("--lines", default=100, type=click.IntRange(min=1))
@pass_state
def search(state: Bootstrap, keyword: str, lines: int) -> None:
    needle = keyword.lower()
    items = [line.rstrip("\r\n") for line in state.store.tail_logs(lines) if needle in line.lower()]
    emit({"items": items}, state, source="configured")


@click.command()
@click.option("--url", required=True, type=HTTP_URL, help="Exact HTTP(S) endpoint to check.")
@click.option("--proxy", default=None, type=HTTP_URL, help="Explicit HTTP proxy; omit for a direct request.")
@pass_state
def health(state: Bootstrap, url: str, proxy: Optional[str]) -> None:
    """Check one URL; no target website or proxy is selected implicitly."""
    emit(check_url(url, proxy, state.deadline.remaining()), state)
