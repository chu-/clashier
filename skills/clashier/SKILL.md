---
name: clashier
description: Inspect Clash Verge subscriptions and query, measure or switch proxy nodes with the Clashier CLI. Use for choosing a subscription or node, changing proxy region, inspecting current selections, or measuring candidate latency.
---

# Clashier

Use the installed `clashier` command on the machine that can reach the intended
Clash Verge / mihomo controller.

This Skill supplies the workflow; the CLI must also be installed. Verify package
availability, Skill discovery and controller access separately. Installation
checks are read-only and do not require changing profiles or nodes.

## Start

Run `clashier --version` and `clashier --output json capabilities` to confirm the
available CLI. For a missing command or installation request, follow the
[installation guide](https://github.com/chu-/clashier/blob/main/docs/install.md).
An absolute executable path works when the Agent's PATH has not refreshed.

Inspect parameters through `clashier RESOURCE ACTION --help`. The available
contracts are exposed by `clashier --output json schema show proxy.select`,
`proxy.list` and `proxy.probe`.
Use global `--output json` for automated resource calls. Default exploration
output is intended for people and includes tables and next-step hints.

## Choose the target

When profile or group names are unknown, use `profile list`, then `profile show UID`
or `proxy list --profile UID` to inspect declared nodes offline. Use exact returned
UIDs/names and present relevant choices to the user. `is_current` is a configured
selection; provider-backed nodes and script/merge effects may not be enumerated.

For a requested profile change, use `profile activate UID`. It restarts the official
client, briefly interrupting networking, and verifies the client-generated runtime
graph. The default budget is 30 seconds; override it with global `--timeout` when
needed. Inspect `client`, `configuration`, `gui_sync` and `verification` separately.
`gui_sync: restarted` with `client.status: ready` means the client restarted with the
selected catalog entry; graph scope is `client_generated_proxy_graph`.
`profile verify UID [--wait]` is read-only and cannot prove GUI state by matching names.
Use `profile activate UID --core-only` only for an explicitly requested core-only
reload: it leaves the GUI unsynchronized. On partial failure, report completed steps
and inspect current state before another write. Website connectivity is separate.

1. Discover controllers with `clashier --output json core discover`. If several
   are reachable, use the intended `--instance ID` for subsequent operations.
2. Use `clashier --output json proxy list` for all live nodes, their direct `groups`
   and `selected_in` arrays. Use `proxy groups` for group names/current choices,
   then `proxy list --group GROUP` for candidates and that group's `data.selected`.
   Put global options before the resource command and use exact returned names.
   Multiple groups may select a node; the all-node list has no single selected value.
3. Match the user's requested node or region to the returned candidates.
   Resolve multiple plausible matches using the user's criteria. Manual selection
   requires a group marked `writable`.

Use resource commands for Agent conversations; `choose` is an optional terminal
menu for humans and is rejected by `--no-input` or a non-terminal input stream.
It saves nodes by default; `choose --temporary` skips saving. Saving requires a
second client restart after the profile was loaded.

## Execute the requested operation

- Inspect: `clashier --output json proxy get --group GROUP`.
- Measure: `clashier --output json proxy probe --group GROUP --name NODE`.
  Measurement does not change selection; check `data.status` for timeout.
- Select: `clashier --output json proxy select --group GROUP --name NODE`.
  Default is runtime-only. Add `--persist` when the user wants the node remembered;
  it saves after client exit, restarts Verge and verifies restoration. Expect a
  brief network interruption; the default persistent-operation budget is 30 seconds.

Pass arguments as an argv array when possible. For structured selection,
use `proxy select --input-json -` with one JSON request on stdin, carrying
`if_current` and the observed `instance_id` / `profile_uid` context when useful.
Read the installed Schema before constructing that request.

## Interpret the result

Read the process exit code and the JSON `ok` field. Successful selection includes
`data.live_status: "verified"`. Persistent success requires
`data.persistence.status: "saved"` and `gui_sync: "restarted"`; a file write alone is
insufficient. Persistence failure can invalidate prior live state after a restart.
Website connectivity and existing connections need separate observation.

If `OUTCOME_UNKNOWN`, `CONCURRENT_MODIFICATION` or `PERSISTENCE_FAILED` is returned,
read the current selection before deciding on another write. Preserve any known
partial effect in the report. For stale context or preconditions, refresh the
group and candidates before acting again.

Report the group, observed node and verification/persistence result. Consult the
[Agent usage guide](https://github.com/chu-/clashier/blob/main/docs/agent-usage.md)
for detailed result handling and other resource operations.
