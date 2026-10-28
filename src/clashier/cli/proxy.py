"""One resource command per proxy operation."""

from typing import Optional

import click

from clashier.adapters.transport import DEFAULT_DELAY_URL
from clashier.bootstrap import Bootstrap
from clashier.cli.protocol import HTTP_URL, select_request
from clashier.cli.render import emit, render_chain, render_choices, render_groups, render_probe, render_selection
from clashier.errors import OperationError

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def proxy() -> None:
    """Inspect, measure and select live proxies."""


@proxy.command()
@click.option("--profile", "profile_name", default=None, help="Read the named profile offline instead of runtime.")
@pass_state
def groups(state: Bootstrap, profile_name: Optional[str]) -> None:
    """List live groups and whether they support manual selection."""
    if profile_name is not None:
        view = state.store.profiles.inspect(profile_name)
        emit({"profile_uid": view["profile_uid"], "items": view["groups"], "view": "declared"},
             state, source="configured", text=render_groups)
        return
    snapshot = state.proxy.snapshot()
    emit({"mode": snapshot.mode, "items": [{"name": item.name, "type": item.kind,
          "selected": item.selected, "writable": item.writable} for item in snapshot.groups.values()]},
         state, text=render_groups)


@proxy.command("list")
@click.option("--group", default=None, help="Limit runtime or declared choices to one named group.")
@click.option("--profile", "profile_name", default=None, help="Read declared nodes from a profile, even if inactive.")
@pass_state
def list_proxies(state: Bootstrap, group: Optional[str], profile_name: Optional[str]) -> None:
    """List all live nodes and their groups, or use --group to list one group's choices."""
    if profile_name is not None:
        view = state.store.profiles.inspect(profile_name)
        items, kind = view["items"], "profile"
        complete = view["complete"]
        if group is not None:
            target = next((item for item in view["groups"] if item["name"] == group), None)
            if target is None:
                raise OperationError("NOT_FOUND", "Group not declared in profile")
            names = {item["name"]: item["type"] for item in view["items"] + view["groups"]}
            names.update({"DIRECT": "Direct", "REJECT": "Reject"})
            items = [{"name": name, "type": names.get(name, "unknown")} for name in target["proxies"]]
            kind, complete = target["type"], not target["dynamic"]
        emit({"profile_uid": view["profile_uid"], "view": "declared", "group": group, "selected": None,
              "type": kind, "writable": False, "items": items, "providers": view["providers"],
              "complete": complete}, state, source="configured", text=render_choices)
        return
    emit(state.proxy.list_proxies(group), state, source="live", text=render_choices)


@proxy.command()
@click.option("--group", required=True)
@pass_state
def get(state: Bootstrap, group: str) -> None:
    """Read the actual selection and its group chain."""
    emit(state.proxy.get(group), state, text=render_chain)


@proxy.command()
@click.option("--group", required=True)
@click.option("--name", required=True)
@click.option("--url", default=None, type=HTTP_URL)
@pass_state
def probe(state: Bootstrap, group: str, name: str, url: Optional[str]) -> None:
    """Measure one candidate without changing the selected node."""
    url = url or state.store.read_config("verge").get("default_latency_test") or DEFAULT_DELAY_URL
    emit(state.proxy.probe(group, name, url, int(state.timeout * 1000)), state, text=render_probe)


@proxy.command()
@click.option("--group", default=None)
@click.option("--name", default=None)
@click.option("--persist", is_flag=True, default=None,
              help="Save in the associated profile and restart the client (brief network interruption).")
@click.option("--if-current", default=None)
@click.option("--input-json", type=str, default=None, help="Request file, or - for stdin.")
@pass_state
def select(state: Bootstrap, group: Optional[str], name: Optional[str], persist: Optional[bool],
           if_current: Optional[str], input_json: Optional[str]) -> None:
    """Set one desired selection, verify it, and optionally persist it."""
    request = select_request(input_json, {"group": group, "name": name,
                                         "persist": persist, "if_current": if_current})
    if request.context is not None:
        requested_instance = request.context["instance_id"]
        if state.instance is not None and state.instance != requested_instance:
            raise OperationError("STALE_CONTEXT", "--instance conflicts with input context")
        state.instance = requested_instance
    emit(state.proxy.select(request), state, text=render_selection)
