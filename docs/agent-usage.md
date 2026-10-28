# Use Clashier from an Agent

For installation or a missing executable, start with [installation](install.md).
Use the installed `clashier` command, or its resolved absolute path, from any
working directory. Run commands on a machine that can access the intended controller.

The Skill and CLI are separate installation components. Skill discovery supplies
the workflow; the installed CLI performs the operations. Verify each component
through [installation](install.md) rather than treating a readable README as an
installed or connected tool.

| Entry | Purpose | Default behavior |
| --- | --- | --- |
| `proxy list` | Explore all live nodes | Direct memberships and selection markers, including loaded provider nodes |
| `proxy list --group G` | Inspect one group's candidates | Its current selection in `data.selected` |
| `proxy groups` | Explore strategy groups | Each group's current choice and manual-selection support |
| `proxy select --group G --name N` | Apply an explicit target without prompts | Runtime-only; `--persist` saves through client restart |
| `choose` | Human terminal wizard | Saves the node; `--temporary` skips node persistence |

## Discover commands on demand

```bash
clashier --help
clashier --output json capabilities
clashier proxy select --help
clashier --output json schema show proxy.select
```

`capabilities` lists implemented operations and platform transports, without
connecting. `schema show` currently supports `proxy.select`, `proxy.list` and
`proxy.probe`; inspect other command parameters through their `--help`.
Help and `--version` return text. Resource operations accept global `--output json`.
Use `--output json` for automated calls: default profile/proxy exploration output
is a human table or summary with next-step hints. JSON envelopes and fields are
independent of that presentation. Hints quote names and retain target options;
authentication values are omitted.

## Find the target and its choices

When the user does not know the subscription or its nodes, start offline:

```bash
clashier --output json profile list
clashier --output json profile show p2
clashier --output json proxy groups --profile p2
clashier --output json proxy list --profile p2
```

Use a returned profile UID or exact name. `is_current` describes catalog selection,
not proven runtime identity. Profile queries return a credential-free declared
view; `--group G` narrows the offline node list to explicit group members.
Provider names and dynamic-group markers disclose what cannot be expanded offline.
No provider is downloaded, and scripts/merges are not evaluated.

For a profile change, use `profile activate UID`. This restarts the official client
and can briefly interrupt networking. The CLI waits for exit before saving the target,
then starts Verge, waits for its read-only PAC availability endpoint and newly generated
configuration, and checks the running graph. The official client applies its native
enhancements and host settings. Activation requires the client's native configuration
directory and the readiness endpoint available in Clash Verge Rev 2.5.7/2.5.8.
The endpoint reflects core availability and does not enable PAC settings. Window
commands are not used for polling. On macOS an exact process check for the current
user precedes direct executable launch; an existing client process is reused.
The default restart budget is 30 seconds; an explicit global `--timeout` overrides it.

Capabilities expose `profile_activation: client_restart`, `profile_loading: verge_startup`
and `profile_core_only: core_api`. Read `data.client`, `data.gui_sync`, `data.configuration`
and `data.verification` separately. `gui_sync: restarted` with `client.status: ready`
means the client restarted with the selected catalog entry. Scope
`client_generated_proxy_graph` compares the client's generated graph with runtime;
it does not test website traffic. A partial result preserves completed steps.
If shutdown fails, the CLI does not write a new catalog selection. If saving after
shutdown fails, it attempts to relaunch the existing configuration.

`profile activate UID --core-only` explicitly skips the client restart. The CLI
renders extensions using embedded V8, sends one core reload request, saves after
acceptance and verifies scope `rendered_proxy_graph`. It leaves `gui_sync: not_verified`;
later GUI operations may reapply the client's in-memory profile. A lost reload response
returns `OUTCOME_UNKNOWN` without changing files. Inspect runtime before retrying.

`profile verify UID [--wait]` remains read-only and renders configured enhancements.
Matching names alone do not identify profile credentials or establish GUI state.
`PROFILE_UNCONFIRMED` reports pending/unconfirmed observations.

The optional `choose [--temporary]` terminal command previews the profile, confirms a
client restart and then presents live groups and nodes. It also restarts when the
catalog already marks that profile current, since catalog/core equality does not
establish the old GUI's selection. Cancelling later preserves completed activation.
The wizard saves the selected node by default after final confirmation, requiring
a second restart after profile activation. `--temporary` skips node persistence,
leaving saved preference unchanged; the profile change still remains active.
Its final node result includes `profile_activation` separately: a node result of
`unchanged` does not mean profile activation was skipped. Agents use resource commands
and present choices in their conversation.

Discover the live choices separately:

```bash
clashier --output json core discover
clashier --output json proxy groups
```

If multiple controllers are reachable, choose the intended instance and pass
`--instance ID` before the resource command. Continue with the same explicit
instance when listing or changing its groups. `core discover` lists candidates;
it does not choose a target on the user's behalf.

List every observed live node without choosing a group:

```bash
clashier --output json proxy list
```

This returns `group: null`, `selected: null`, `view: live`, the runtime `mode`, and
one item per node with `groups` and `selected_in` arrays. These arrays describe
**direct** membership and selection; group entries themselves are excluded from
the all-node list. Unreferenced nodes remain visible with empty arrays. Built-in
actions and loaded provider nodes are included. These are observed candidates,
not a connectivity result or proof of a single global traffic path.

List a group's candidates using a name from `proxy groups`:

```bash
clashier --output json proxy list --group 'Example Selector'
```

The names in these examples are illustrative. Use exact names returned by the
controller. Group lists include `writable`; manual selection supports Selector
groups. A regional request may match several candidates, so use the user's
selection criteria or resolve the ambiguity before writing.

## Measure or select

Measurement leaves the selection unchanged:

```bash
clashier --output json proxy probe --group 'Example Selector' --name 'Example Node A'
```

`data.status` distinguishes `reachable` from `timeout`; `latency_ms: 0` is valid.
A completed measurement can exit 0 even when the measured candidate times out.

Selection sets one exact target and verifies it:

```bash
clashier --output json proxy select --group 'Example Selector' --name 'Example Node A'
```

Add `--persist` when the user wants the choice remembered in the associated
Verge profile. Runtime-only is the default for `proxy select`. Persistent selection
requires the installed official client and native configuration directory, and
restarts it after saving the preference while the client is stopped. The operation
budget defaults to 30 seconds; an explicit global timeout covers the live change
and persistence together without resetting between phases.

Report `persistence.status: saved` only after file readback, client restart and
runtime restoration are verified. Results include `persistence.method: client_restart`,
`persistence.gui_sync: restarted` and `persistence.client.status: ready`.
If persistence fails after shutdown began, the prior runtime observation may no
longer hold: `live_status: unknown` and `after: null` preserve that uncertainty.
`persistence.client_activation` records completed restart effects on failure.
Inspect current state before another write. Selecting a node does not verify a
website or move existing connections.

For a fresh observation:

```bash
clashier --output json proxy get --group 'Example Selector'
```

## Pass structured requests

`proxy select --input-json -` accepts one JSON object on stdin. Alternatively,
use `--input-json request.json`. JSON input replaces the command's selection
flags; global options still precede `proxy`.

This Python example works with POSIX shells and PowerShell callers. Replace the
illustrative names with values already observed from the controller:

```python
import json
import subprocess

result = subprocess.run(
    ["clashier", "--output", "json", "proxy", "select", "--input-json", "-"],
    input=json.dumps({"group": "Example Selector", "name": "Example Node A"}),
    text=True,
    encoding="utf-8",
    capture_output=True,
    timeout=15,
)
value = json.loads(result.stdout)
if result.returncode != 0 or value["ok"] is not True:
    raise RuntimeError(value["error"])
print(value["data"])
```

When producing a request from `proxy list --group G`, carry `data.selected` into
`if_current`, and the returned `context.instance_id` and `context.profile_uid`
into `context`. These fields bind the request to the observed target. The
context can also contain observation metadata; send only those two identity fields.
See the [shell composition example](../examples/select-reachable.sh) for a complete pipeline.

## Read results and recover

Resource output is one UTF-8 JSON object with `schema_version`, `ok`, `data`,
`error`, `context` and `meta`. Diagnostics are on stderr. Exit codes are
0 for success, 1 for operation failure, 2 for invalid input, and 130 for interruption.

| Result | Next action |
| --- | --- |
| `INVALID_ARGUMENT` | Read command help or the available Schema and correct the input |
| `NOT_FOUND` | Refresh groups or candidates and use an exact returned name |
| `AMBIGUOUS_TARGET` | Select the intended discovered instance |
| `STALE_CONTEXT` / `PRECONDITION_FAILED` | Refresh the observation before deciding whether to select again |
| `OUTCOME_UNKNOWN` / `CONCURRENT_MODIFICATION` | Read `proxy get` before deciding on another write |
| `PERSISTENCE_FAILED` | Report the partial result, read live state, then retry the same desired selection if still intended |
| `PROFILE_UNCONFIRMED` | Report configured selection and observation status; check Verge reload and rerun `profile verify UID` before selecting |
| `UNSUPPORTED_OPERATION` | Check the group, profile association or platform transport requirement |
| Controller connection/authentication failure | Inspect controller access and configuration; retain the returned error code |

Configured-file queries identify their source as `data.source: "configured"`.
Management writes can return `status: "pending"` until Verge reloads them.
For normal proxy tasks use summary queries. `config get` explicitly exports raw
configuration, which can contain credentials.

Report the requested group, observed selected node, verification state and any
requested persistence result. If an operation is partial or unknown, preserve
that distinction in the final response.
