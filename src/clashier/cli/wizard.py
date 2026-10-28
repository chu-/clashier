"""Optional terminal prompts composed from profile and proxy operations."""

import sys
from collections import Counter
from contextlib import redirect_stdout
from typing import Any, Dict, List

import click

from clashier.application.profiles import ProfileControl
from clashier.bootstrap import Bootstrap
from clashier.cli.render import emit, group_mode, render_profile, render_selection, table
from clashier.errors import OperationError
from clashier.models import SelectRequest


def _pick(label: str, items: List[Dict[str, Any]], *, current_label: str = "current") -> Dict[str, Any]:
    if not items:
        raise OperationError("NOT_FOUND", "No {} available".format(label))
    click.echo(label + ":", err=True)
    names = Counter(item.get("name") for item in items)
    for index, item in enumerate(items, 1):
        marker = " [{}]".format(current_label) if item.get("is_current") else ""
        identity = " ({})".format(item["uid"]) if "uid" in item and names[item.get("name")] > 1 else ""
        selected = " -> {}".format(item["selected"]) if item.get("selected") is not None else ""
        description = " [{}]".format(item["description"]) if item.get("description") else ""
        click.echo("  {}. {}{}{}{}{}".format(index, item.get("name") or item.get("uid"),
                                          identity, description, selected, marker), err=True)
    # Click 8.1's input spacer is written to stdout even with err=True.
    with redirect_stdout(sys.stderr):
        index = click.prompt("Choose a number", type=click.IntRange(1, len(items)), err=True)
    return items[index - 1]


def _terminal_available() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def _confirm(message: str) -> None:
    with redirect_stdout(sys.stderr):
        click.confirm(message, abort=True, err=True)


def _activate_profile(state: Bootstrap, view: Dict[str, Any]) -> Dict[str, Any]:
    click.echo("\nClash Verge will restart to load this profile and synchronize its client state.", err=True)
    click.echo("Networking may briefly stop. Cancelling later does not undo this profile change.", err=True)
    _confirm("Activate this profile and restart Clash Verge?")
    state.refresh_runtime()
    result = ProfileControl(state).activate(view["profile_uid"])
    click.echo("Clash Verge restarted; its generated configuration matches the running core.", err=True)
    return result


@click.command()
@click.option("--temporary", is_flag=True, help="Change the live node without saving it in the profile.")
@click.pass_obj
def choose(state: Bootstrap, temporary: bool) -> None:
    """Choose a profile and node, saving the node by default; use --temporary to skip saving."""
    if state.no_input or not _terminal_available():
        raise click.UsageError("choose requires a terminal and cannot be used with --no-input; use resource commands")
    items = [{key: entry.get(key) for key in ("uid", "name", "is_current")}
             for entry in state.store.profiles.list() if entry.get("type") in ("remote", "url", "local")]
    selected_profile = _pick("Profiles", items, current_label="configured current")
    uid = selected_profile["uid"]
    view = state.store.profiles.inspect(uid)
    click.echo("\nSelected profile (configuration preview):", err=True)
    with redirect_stdout(sys.stderr):
        render_profile(view, next_steps=False)
    # Catalog/core equality cannot establish the old client's in-memory selection.
    activation = _activate_profile(state, view)
    click.echo("Rendered proxy graph matches runtime; website connectivity has not been tested.",
               err=True)
    state.renew_deadline()
    groups = state.proxy.snapshot().groups.values()
    group = _pick("Live Selector groups", [{"name": item.name, "selected": item.selected,
                                           "description": group_mode(item.kind)}
                                         for item in groups if item.writable])["name"]
    state.renew_deadline()
    choices = state.proxy.list_proxies(group)
    candidate = _pick("Live candidates", [dict(item, is_current=item["name"] == choices["selected"],
                                              description="Direct (no proxy)" if item["name"] == "DIRECT"
                                              else item["type"])
                                         for item in choices["items"]])["name"]
    context = state.proxy.context()
    if context["profile_uid"] != uid:
        raise OperationError("STALE_CONTEXT", "Profile changed while choosing")
    click.echo("\nReview selection:", err=True)
    with redirect_stdout(sys.stderr):
        table(["Setting", "Value"], [
            ["Profile", view["name"] or uid], ["Group", group],
            ["Current node", choices["selected"] or "(none)"], ["Requested node", candidate],
            ["Remember selection", "No (temporary)" if temporary else "Yes (restart to save)"],
        ])
    if not temporary:
        click.echo("Saving the node will restart Clash Verge once more; networking may briefly stop.", err=True)
    _confirm("Apply this selection?")
    state.renew_deadline()
    result = state.proxy.select(SelectRequest(group, candidate, not temporary, choices["selected"], context))
    result["profile_activation"] = activation
    emit(result, state, text=render_selection)
