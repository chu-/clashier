"""Subscription profile commands."""

from typing import Optional

import click

from clashier.adapters.web import download_subscription
from clashier.application.profiles import ProfileControl
from clashier.bootstrap import Bootstrap
from clashier.cli.protocol import HTTP_URL
from clashier.cli.render import emit, render_profile, render_profile_state, render_profiles
from clashier.errors import OperationError

pass_state = click.make_pass_decorator(Bootstrap)


@click.group()
def profile() -> None:
    """List and manage subscription profiles."""


@profile.command("list")
@pass_state
def list_profiles(state: Bootstrap) -> None:
    """List profile identities without exposing subscription URLs."""
    items = [{"uid": item.get("uid"), "name": item.get("name") or item.get("file"),
              "type": item.get("type"), "is_current": item["is_current"]}
             for item in state.store.profiles.list()]
    emit({"items": items}, state, source="configured", text=render_profiles)


@profile.command()
@click.argument("name")
@pass_state
def show(state: Bootstrap, name: str) -> None:
    """Inspect a profile's declared groups, nodes and provider names offline."""
    emit(state.store.profiles.inspect(name), state, text=render_profile)


@profile.command()
@click.argument("name")
@click.option("--core-only", is_flag=True, help="Hot-load only the core; the client profile is not synchronized.")
@pass_state
def activate(state: Bootstrap, name: str, core_only: bool) -> None:
    """Select a profile, restart the official client and verify its runtime configuration."""
    emit(ProfileControl(state).activate(name, core_only=core_only), state, text=render_profile_state)


@profile.command()
@click.argument("name")
@click.option("--wait", is_flag=True, help="Observe until the global timeout expires.")
@pass_state
def verify(state: Bootstrap, name: str, wait: bool) -> None:
    """Compare declared nodes and groups with runtime; no reload or writes."""
    emit(ProfileControl(state).verify(name, wait=wait), state, text=render_profile_state)


@profile.command()
@click.argument("url", type=HTTP_URL)
@click.option("--name", default=None)
@pass_state
def add(state: Bootstrap, url: str, name: Optional[str]) -> None:
    """Download and save one subscription profile."""
    content = download_subscription(url, state.deadline.remaining())
    item = state.store.profiles.import_subscription(url, content, name)
    emit({"status": "saved", "profile_uid": item["uid"], "name": item["name"]}, state, source="configured")


@profile.command()
@click.argument("name")
@pass_state
def delete(state: Bootstrap, name: str) -> None:
    """Delete an inactive profile and its file."""
    target = state.store.profiles.find(name)
    if not target:
        raise OperationError("NOT_FOUND", "Profile '{}' not found".format(name))
    state.store.profiles.delete(target["uid"])
    emit({"status": "deleted", "profile_uid": target["uid"]}, state, source="configured")


@profile.command()
@pass_state
def traffic(state: Bootstrap) -> None:
    """Read subscription usage recorded in the active profile."""
    stats = state.store.profiles.subscription_usage()
    if not stats:
        raise OperationError("NOT_FOUND", "No active profile")
    emit(stats, state, source="configured")
