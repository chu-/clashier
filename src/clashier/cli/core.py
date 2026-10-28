"""Discovery, capabilities and schemas for command callers."""

import click

from clashier.adapters.discovery import discover
from clashier.bootstrap import Bootstrap
from clashier.cli.protocol import SCHEMAS, load_schema
from clashier.cli.render import emit, render_groups
from clashier.errors import OperationError

pass_state = click.make_pass_decorator(Bootstrap)


@click.command()
@pass_state
def status(state: Bootstrap) -> None:
    """Report observed runtime status instead of inferring it from a YAML file."""
    snapshot = state.proxy.snapshot()
    emit({"mode": snapshot.mode, "controller": "reachable",
          "items": [{"name": group.name, "selected": group.selected,
                     "type": group.kind, "writable": group.writable} for group in snapshot.groups.values()]},
         state, text=render_groups)


@click.group(invoke_without_command=True)
@click.pass_context
def core(ctx: click.Context) -> None:
    """Discover controllers; without a subcommand show the configured core."""
    if ctx.invoked_subcommand is None:
        state = ctx.obj
        name = state.store.read_config("verge").get("clash_core", "verge-mihomo")
        emit({"core": name}, state, source="configured")


@core.command("discover")
@pass_state
def discover_command(state: Bootstrap) -> None:
    """List verified controllers and reasons other candidates failed."""
    endpoints = state.endpoints()
    if state.instance:
        endpoints = [item for item in endpoints if item.instance_id == state.instance]
        if not endpoints:
            raise OperationError("NOT_FOUND", "Controller instance not found")
    reachable, failures = discover(endpoints, state.deadline)
    data = {"items": [{"instance_id": item.instance_id, "source": item.source,
                      "transport": "unix" if item.address.startswith("unix://") else "tcp"}
                     for item in reachable], "failures": failures}
    if not reachable:
        raise OperationError("CONTROLLER_UNAVAILABLE", "No reachable Clash controller", data=data,
                             safe_to_retry=True)
    emit(data, state)


@click.command()
@pass_state
def capabilities(state: Bootstrap) -> None:
    """Describe implemented features without connecting to a controller."""
    emit({"schema_versions": ["1"], "transports": ["tcp", "unix"] if state.platform != "windows" else ["tcp"],
          "operations": ["core.discover", "status", "proxy.groups", "proxy.list", "proxy.get",
                         "proxy.probe", "proxy.select", "profile.list", "profile.show", "profile.verify",
                         "profile.add", "profile.activate", "choose",
                         "profile.delete", "profile.traffic", "host.proxy.get", "host.proxy.set",
                         "host.tun.get", "host.tun.set", "host.ports.get", "host.ports.set",
                         "host.restart", "host.open", "host.webui", "backup.list", "backup.create",
                         "backup.restore", "config.get", "config.set", "config.path", "config.dns",
                         "config.rules", "config.refresh", "logs.read", "logs.search", "health"],
          "persistence": "associated-verge-profile", "persistence_method": "client_restart", "named_pipe": False,
          "choose_default": "persist", "choose_temporary": True,
          "profile_views": ["declared", "live"], "interactive": "choose",
          "profile_activation": "client_restart", "profile_loading": "verge_startup",
          "profile_core_only": "core_api", "profile_verification": "client_generated_proxy_graph"}, state)


@click.group()
def schema() -> None:
    """Inspect the installed machine-readable command contracts."""


@schema.command()
@click.argument("operation", type=click.Choice(sorted(SCHEMAS)))
@pass_state
def show(state: Bootstrap, operation: str) -> None:
    """Show input and result schemas; no runtime or configuration is needed."""
    name = SCHEMAS[operation]
    emit({"operation": operation, "input": load_schema(name + "-input") if operation == "proxy.select" else None,
          "result": load_schema(name + "-result"), "envelope": load_schema("result")}, state)
