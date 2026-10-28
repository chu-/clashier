"""The single stdout/stderr renderer for all CLI resources."""

import json
import shlex
import sys
import unicodedata
from collections import Counter
from contextlib import redirect_stdout
from typing import Any, Callable, Dict, List, Optional, Sequence

import click

from clashier.bootstrap import Bootstrap
from clashier.cli.protocol import envelope
from clashier.errors import OperationError


def emit(data: Dict[str, Any], state: Bootstrap, source: Optional[str] = None,
         text: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
    """Render a human summary or exactly one machine result, depending on output mode."""
    if source is not None:
        data = dict(data, source=source)
    if state.output == "json":
        click.echo(json.dumps(envelope(data, state), ensure_ascii=False))
    elif text is not None:
        text(data)
    else:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def emit_error(error: OperationError, state: Optional[Bootstrap], json_mode: bool) -> None:
    """Keep diagnostics on stderr, with a structured error on stdout in JSON mode."""
    click.echo(str(error), err=True)
    if json_mode:
        click.echo(json.dumps(envelope(error.data, state, error), ensure_ascii=False))
    elif error.data:
        with redirect_stdout(sys.stderr):
            if "verification" in error.data:
                render_profile_state(error.data)
            elif "live_status" in error.data:
                render_selection(error.data)
            click.echo("Keep the same global connection options when retrying.")


def _authenticated_controller(value: str) -> bool:
    return "@" in value.split("://", 1)[-1].split("/", 1)[0]


def command_hint(*arguments: str) -> str:
    """Quote returned names for the host's POSIX shell or Windows PowerShell."""
    context = click.get_current_context(silent=True)
    options = []
    if context is not None:
        parameters = context.find_root().params
        for name in ("config_dir", "controller", "instance"):
            value = parameters.get(name)
            if value is not None:
                if name == "controller" and _authenticated_controller(value):
                    continue
                options.extend(["--" + name.replace("_", "-"), value])
        if parameters.get("timeout") is not None and "--timeout" not in arguments:
            options.extend(["--timeout", str(parameters["timeout"])])
    arguments = (*options, *arguments)
    if sys.platform == "win32":
        return "clashier " + " ".join("'{}'".format(value.replace("'", "''")) for value in arguments)
    return shlex.join(["clashier", *arguments])


def _width(value: str) -> int:
    return sum(0 if unicodedata.category(char) in ("Mn", "Me", "Cf") else
               2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in value)


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    def cell(value: Any) -> str:
        return str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

    values = [[cell(value) for value in row] for row in [headers, *rows]]
    widths = [max(_width(row[index]) for row in values) for index in range(len(headers))]
    for row in values:
        click.echo("  ".join(value + " " * (widths[index] - _width(value))
                             for index, value in enumerate(row)).rstrip())
    if not rows:
        click.echo("  (none)")


def group_mode(kind: str) -> str:
    return {"select": "Manual selection", "selector": "Manual selection", "url-test": "Automatic latency",
            "urltest": "Automatic latency", "fallback": "Failover", "load-balance": "Load balance",
            "loadbalance": "Load balance", "relay": "Proxy chain"}.get(kind.lower(), kind)


def _node_type(kind: str) -> str:
    return {"direct": "Direct (no proxy)", "reject": "Block", "ss": "Shadowsocks",
            "ssr": "ShadowsocksR", "select": "Manual group", "selector": "Manual group",
            "url-test": "Automatic group", "urltest": "Automatic group", "fallback": "Failover group",
            "load-balance": "Load-balance group", "loadbalance": "Load-balance group"}.get(kind.lower(), kind)


def _next(label: str, *arguments: str) -> None:
    context = click.get_current_context(silent=True)
    parameters = context.find_root().params if context is not None else {}
    if arguments == ("choose",) and parameters.get("no_input"):
        return
    click.echo("\n{}:\n  {}".format(label, command_hint(*arguments)))
    if parameters.get("secret"):
        click.echo("  Keep CLASH_API_SECRET set for follow-up commands; secrets are not printed.")
    controller = parameters.get("controller") or ""
    if _authenticated_controller(controller):
        click.echo("  Retain your authenticated --controller option; it is omitted here.")


def _configured_note() -> None:
    click.echo("Source: declared configuration (offline; not runtime).")
    click.echo("Providers are not expanded; scripts and merges may change the running graph.")


def render_profiles(data: Dict[str, Any]) -> None:
    items = data["items"]
    names = Counter(item["name"] for item in items)
    rows = []
    for item in items:
        name = item["name"] or item["uid"]
        if names[item["name"]] > 1:
            name += " ({})".format(item["uid"])
        rows.append([name, item["type"], "Current (configured)" if item["is_current"] else "Inactive"])
    table(["Profile", "Type", "Selection"], rows)
    click.echo("\nThe configured current profile is not proof of runtime loading.")
    selectable = [item for item in items if item["type"] in ("remote", "url", "local")]
    if selectable:
        target = next((item for item in selectable if not item["is_current"]), selectable[0])
        _next("Inspect a profile (use its exact name or UID)", "profile", "show", target["uid"])
        _next("Explore interactively", "choose")
    else:
        click.echo("\nNo selectable profiles. Import one with: clashier profile add URL --name NAME")


def _declared_groups(groups: List[Dict[str, Any]]) -> None:
    table(["Group", "Mode", "Declared choices", "Provider sources"], [
        [group["name"], group_mode(group["type"]),
         str(len(group["proxies"])) + (" + dynamic" if group["dynamic"] else ""),
         ", ".join(group["use"]) or "-"] for group in groups])


def render_profile(data: Dict[str, Any], *, next_steps: bool = True) -> None:
    click.echo("Profile: {}\nUID: {}".format(data["name"] or data["profile_uid"], data["profile_uid"]))
    click.echo("Selection: {}".format("Current (configured)" if data["is_current"] else "Inactive"))
    _configured_note()
    click.echo("\nDeclared groups:")
    _declared_groups(data["groups"])
    click.echo("\nDirectly declared nodes: {}".format(len(data["items"])))
    table(["Node", "Type"], [[item["name"], _node_type(item["type"])] for item in data["items"]])
    if data["providers"]:
        click.echo("\nProviders (not expanded): " + ", ".join(item["name"] for item in data["providers"]))
    if not data["complete"]:
        click.echo("Dynamic content: this offline view cannot enumerate every candidate.")
    if next_steps:
        if data["groups"]:
            _next("Inspect declared group choices", "proxy", "list", "--profile", data["profile_uid"],
                  "--group", data["groups"][0]["name"])
        else:
            _next("Inspect declared nodes", "proxy", "list", "--profile", data["profile_uid"])
        _next("Explore interactively", "choose")


def render_groups(data: Dict[str, Any]) -> None:
    if data.get("source") == "configured":
        click.echo("Profile UID: " + data["profile_uid"])
        _configured_note()
        _declared_groups(data["items"])
        if data["items"]:
            _next("Inspect declared choices", "proxy", "list", "--profile", data["profile_uid"],
                  "--group", data["items"][0]["name"])
        return
    click.echo("Source: running controller\nMode: " + data["mode"])
    table(["Group", "Mode", "Selected", "Manual selection"], [
        [item["name"], group_mode(item["type"]), item["selected"] or "(none)",
         "Yes" if item["writable"] else "No"] for item in data["items"]])
    if data["items"]:
        group = next((item for item in data["items"] if item["writable"]), data["items"][0])
        _next("Inspect live candidates", "proxy", "list", "--group", group["name"])


def render_choices(data: Dict[str, Any]) -> None:
    configured = data.get("source") == "configured"
    if configured:
        click.echo("Profile UID: " + data["profile_uid"])
        _configured_note()
    else:
        click.echo("Source: running controller")
    if not configured and data["group"] is None:
        click.echo("Mode: {}\nScope: all live nodes".format(data["mode"]))
        table(["Node", "Type", "Member of", "Selected by"], [
            [item["name"], _node_type(item["type"]), ", ".join(item["groups"]) or "-",
             ", ".join(item["selected_in"]) or "-"] for item in data["items"]])
        click.echo("\nMembership and selection show direct group relationships; connectivity was not tested.")
        _next("Inspect groups and their current choices", "proxy", "groups")
        return
    if data["group"] is not None:
        click.echo("Group: " + data["group"])
    click.echo("Current selection: " + ("not observed (offline)" if configured else data["selected"] or "(none)"))
    table(["Node / group", "Type", "Selection"], [
        [item["name"], _node_type(item["type"]),
         "Current" if not configured and item["name"] == data["selected"] else "-"] for item in data["items"]])
    if configured:
        if not data["complete"]:
            click.echo("\nDynamic candidates are not expanded in this offline view.")
        if data["providers"]:
            click.echo("Providers: " + ", ".join(item["name"] for item in data["providers"]))
        _next("Load this profile by restarting Clash Verge (brief network interruption)", "--timeout", "30", "profile",
              "activate", data["profile_uid"])
        _next("Explore interactively", "choose")
    elif data["writable"]:
        if data["items"]:
            target = next((item for item in data["items"] if item["name"] != data["selected"]), data["items"][0])
            _next("Select a candidate (replace the example name with your choice)",
                  "proxy", "select", "--group", data["group"], "--name", target["name"])
        else:
            click.echo("\nNo live candidates are available.")
    else:
        click.echo("\nThis group does not support manual selection.")
        _next("Read the selected group chain", "proxy", "get", "--group", data["group"])


def render_chain(data: Dict[str, Any]) -> None:
    click.echo("Source: running controller\nGroup: {}\nSelected: {}".format(
        data["group"], data["selected"] or "(none)"))
    click.echo("Chain: " + " -> ".join(data["chain"]))
    if not data["resolved"]:
        click.echo("Chain is unresolved: " + data.get("reason", "unknown target"))
    _next("Explore live candidates", "proxy", "list", "--group", data["group"])


def render_probe(data: Dict[str, Any]) -> None:
    click.echo("Group: {}\nCandidate: {}".format(data["group"], data["name"]))
    click.echo("Latency: {}".format("{} ms".format(data["latency_ms"])
                                    if data["status"] == "reachable" else "Timed out"))
    click.echo("Selection was not changed.")


def render_selection(data: Dict[str, Any]) -> None:
    if "profile_activation" in data:
        activation = data["profile_activation"]
        click.echo("Profile: {}\nVerge client: restarted and ready".format(
            activation["name"] or activation["profile_uid"]))
    click.echo("Group: {}\nSelection: {} -> {}".format(data["group"], data["before"] or "(none)",
                                                    data["after"] or "(unknown)"))
    click.echo("Result: {}\nLive verification: {}\nPersistence: {}".format(
        data["status"], data["live_status"], data["persistence"]["status"]))
    if data["persistence"].get("gui_sync") == "restarted":
        click.echo("Node memory: saved in the profile and loaded by the restarted client.")
    elif not data["persistence"]["requested"]:
        click.echo("Node memory: saved preference unchanged (temporary selection).")
    click.echo("Website connectivity was not tested.")
    _next("Read current selection", "proxy", "get", "--group", data["group"])


def render_profile_state(data: Dict[str, Any]) -> None:
    status = {"pending": "Waiting for core confirmation", "unconfirmed": "Not confirmed",
              "verified": "Rendered graph matched", "partial": "Partially applied",
              "unknown": "Outcome unknown", "not_applied": "Not applied"}.get(data["status"], data["status"])
    click.echo("Profile: {} ({})\nResult: {}".format(data["name"] or data["profile_uid"],
                                                   data["profile_uid"], status))
    verification = data["verification"]
    observed = {"not_requested": "Not checked", "matched": "Declared graph matches", "different": "Different graph",
                "inconclusive": "Cannot establish a match", "unavailable": "Controller observation unavailable"}
    click.echo("Runtime observation: " + observed[verification["status"]])
    if "reload" in data:
        click.echo("Core reload: {}\nConfiguration: {}".format(data["reload"]["status"],
                                                              data["configuration"]["status"]))
        if data.get("gui_sync") == "restarted":
            click.echo("Verge client: restarted and ready with the selected profile.")
        elif "client" in data:
            click.echo("Verge client: " + data["client"]["status"])
        else:
            click.echo("Verge GUI selection: not synchronized (--core-only).")
    if verification.get("reason"):
        reasons = {"profile_not_current": "This profile is not selected in the catalog.",
                   "dynamic_or_empty_graph": "Empty or dynamic declarations cannot be verified by this comparison.",
                   "declared_graph_not_observed": "The running graph does not match the declared nodes and groups.",
                   "saved_selection_not_observed": "The client has not restored the saved node in runtime.",
                   "CONTROLLER_UNAVAILABLE": "The controller could not be reached.",
                   "DEADLINE_EXCEEDED": "The observation timed out.",
                   "AUTH_FAILED": "Controller authentication failed."}
        click.echo("Reason: " + reasons.get(verification["reason"], verification["reason"]))
    click.echo("Verification compares rendered node types, group membership and mode; website traffic is not tested.")
    if data["status"] == "verified":
        _next("Explore live groups", "proxy", "groups")
    elif data.get("reload", {}).get("status") == "unknown":
        _next("Inspect runtime before deciding on another write", "status")
    elif verification.get("reason") == "dynamic_or_empty_graph":
        click.echo("An empty graph cannot identify a loaded profile without an accepted reload request.")
        _next("Explore live groups", "proxy", "groups")
    else:
        click.echo("Configured selection does not prove the profile is running.")
        if verification["status"] in ("not_requested", "different") or (
            verification.get("reason") == "profile_not_current"
        ):
            _next("Load the profile and restart Clash Verge", "--timeout", "30", "profile", "activate",
                  data["profile_uid"])
        _next("Read-only verification", "--timeout", "20", "profile", "verify", data["profile_uid"], "--wait")


def configure_console() -> None:
    """Preserve Unicode data when a pipe or Windows console uses another encoding."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
