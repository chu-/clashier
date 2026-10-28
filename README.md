# Clashier: Proxy control

Clashier provides composable local proxy operations for shells and agents. Query, measure and select
nodes through a running Clash Verge / mihomo controller over TCP or Unix sockets.

The project includes a CLI for executing operations and an optional Agent Skill
for discovering the right commands and following the proxy workflow.

English | [简体中文](README.zh-CN.md)

## Quick start

### Install the CLI

Install from [GitHub](https://github.com/chu-/clashier) with
[uv](https://docs.astral.sh/uv/getting-started/installation/) and Git:

```bash
uv tool install 'git+https://github.com/chu-/clashier.git'
clashier --version
clashier --output json capabilities
```

The command works from any directory. Python 3.8+ is required; pass
`--python 3.12` to `uv tool install` to request a managed interpreter.
See the [installation guide](docs/install.md) for Windows, PATH, updates and verification.

### Agent-assisted installation

Give Codex, Claude Code or another Agent with access to the target computer's
terminal the repository URL or this README, together with this request:

> Install the Clashier CLI from https://github.com/chu-/clashier and register
> its skills/clashier directory as a user-level Skill for your Agent host.
> Follow docs/install.md. Verify the CLI, Skill discovery and controller access
> separately, and report the executable path, Skill location and results.

**For installation Agents:** follow the
[installation guide](https://github.com/chu-/clashier/blob/main/docs/install.md).
It provides CLI-only, CLI-plus-Skill and local-checkout instructions. Then use
[Agent usage](https://github.com/chu-/clashier/blob/main/docs/agent-usage.md)
for command discovery and JSON results. The
[Skill entry](https://github.com/chu-/clashier/blob/main/skills/clashier/SKILL.md)
is separate from this README; installing the CLI alone does not register a Skill.

GitHub installation requires a published repository and read access. A complete
local checkout can be installed before publication. Installation checks are
read-only and do not require switching profiles, restarting Verge or changing
nodes. The Agent needs execution access on the target computer; reading a README
in a chat alone does not grant access to its local proxy.

## Command guide

### Find a subscription and its nodes

Start with the catalog when you do not know the profile or group names:

```bash
clashier profile list
clashier profile show p2
clashier proxy groups --profile p2
clashier proxy list --profile p2
clashier proxy list --profile p2 --group 'Example Selector'
```

By default, these exploration commands show tables, current/configured markers
and copyable next-step commands. Names are enough for normal use; duplicate names
show UIDs, and `profile show` always includes the UID. Add global `--output json`
for stable machine results, for example `clashier --output json profile list`.
Follow-up hints retain connection options and omit authentication values.

Replace the illustrative `p2` with a profile's UID or exact name. These queries work for
inactive profiles without connecting to the controller or changing selection.
Text identifies the offline source; JSON reports `source: configured` and `view: declared`. Node credentials and
provider URLs are omitted. Providers are listed by name, not downloaded or expanded.
`complete: false` identifies provider or dynamic-group content that the static
view cannot enumerate. Verge scripts and merges can also change the final graph.

To load another profile directly from the CLI:

```bash
clashier profile activate p2
clashier profile verify p2
```

Activation stops the official Clash Verge client and waits for it to exit, then
saves the target profile and starts the client again. Writing after exit prevents
the client's shutdown save from restoring its old selection. Clash Verge renders
its own scripts, merges, DNS and TUN settings. The CLI waits for client readiness,
a newly generated configuration and a matching runtime graph before reporting success.

Readiness is observed through the official client's read-only PAC endpoint, available
in Clash Verge Rev 2.5.7 and 2.5.8. Its availability follows core readiness; this does
not enable system PAC settings or request window creation. On macOS an exact process
check for the current user prevents duplicate launches; the executable is started
directly when no client process exists. A restart briefly interrupts networking. The default budget
is 30 seconds for activation; an explicit global `--timeout` overrides it.
`gui_sync: restarted` and `client.status: ready` describe the completed client restart.
The verification scope is `client_generated_proxy_graph`; website traffic is not tested.
Startup or verification failures report the completed steps and a partial effect.

`profile verify UID [--wait]` is a read-only graph comparison including configured
enhancements; matching names alone cannot prove the client's in-memory selection.
For an explicit core-only operation, use `profile activate UID --core-only`. This
renders extensions in the CLI (JavaScript uses embedded V8, without Node.js),
hot-loads mihomo and saves configuration, but leaves `gui_sync: not_verified`.
Scripts must synchronously return a configuration object; console output is discarded.
A lost core reload response reports an unknown outcome without changing files.

For a terminal menu:

```bash
clashier choose
```

`choose` is the terminal wizard. `proxy select --group G --name N` is the
non-interactive operation for an already known target, suitable for scripts and Agents.

Choose a profile, a live Selector group and a candidate by number. The selected
profile's declared groups/nodes are previewed first. After confirmation the wizard
restarts Clash Verge with that profile, including when the catalog already marks it
current: the old GUI may have held a different in-memory selection. It then offers
live groups and candidates. Cancelling later leaves the completed activation in place.
The final review shows the profile, group, old/new node and saving choice.
`choose` saves the node by default: after the final confirmation it stops the client,
writes the selected node after exit, restarts Verge and verifies the restored node.
This requires a second restart after loading the profile, so it briefly interrupts
networking again. Use `clashier choose --temporary` for a runtime-only node choice;
the saved preference is left unchanged. The flag applies to the node, while the
chosen profile remains active.

Prompts go to stderr and the final result goes to stdout. `choose` requires a
terminal; `--no-input` rejects it. Agents use the resource commands above.

### Proxy discovery and node selection

Global options go **before** the command. The group and node names below are
synthetic examples; replace them with values returned by your controller:

```bash
clashier --output json proxy groups
clashier --output json proxy list
clashier --output json proxy list --group 'Example Selector'
clashier --output json proxy probe --group 'Example Selector' --name 'Example Node A'
clashier --output json proxy select --group 'Example Selector' --name 'Example Node A' --persist
clashier --output json proxy get --group 'Example Selector'
```

| Command | Effect |
| --- | --- |
| `core discover` | List verified controller instances and failed candidate diagnostics |
| `status` | Observe the running mode and live group selections |
| `proxy groups [--profile UID]` | List live groups, or a profile's declared groups offline |
| `proxy list [--group G]` / `proxy list --profile UID [--group G]` | List all live nodes with group/selection markers, one group's candidates, or declared profile nodes |
| `proxy get --group G` | Read a group's selection and selected group chain |
| `proxy probe --group G --name N [--url URL]` | Measure one candidate without changing selection |
| `proxy select --group G --name N [--persist] [--if-current OLD]` | Set and verify one selection |
| `capabilities` | Describe implemented operations and transports without connecting |
| `schema show proxy.select` | Inspect the installed request and result contracts |

`proxy list` lists all nodes observed in the running configuration, including loaded
provider nodes and built-in actions, with their direct group memberships and the
groups currently selecting them. Strategy groups themselves are listed by
`proxy groups`; a node can belong to, or be selected by, several groups.
`proxy list --group G` lists that group's candidates, including nested groups,
and marks its current choice. Listing does not test connectivity.

`proxy select` is runtime-only by default. Add `--persist` to remember the node
in the associated official client: it waits for client exit, saves the preference,
restarts the client and verifies the restored node. Persistence requires the native
configuration directory and installed client; its default operation budget is 30
seconds. A successful result includes `persistence.status: saved` and
`persistence.gui_sync: restarted`. File writes alone are not treated as durable success.
Repeating a request skips a redundant node PUT, but requested persistence still
restarts the client to synchronize its memory. Automatic groups are not treated as
writable selectors.

### Controller discovery and connection settings

| Global option | Environment | Meaning |
| --- | --- | --- |
| `--config-dir PATH` | `CLASH_VERGE_DIR` | Verge config directory; platform detection by default |
| `--controller ADDRESS` | `CLASH_API_URL` | Explicit HTTP(S) URL, host:port, or `unix:///absolute/socket` |
| `--secret TEXT` | `CLASH_API_SECRET` | Controller secret; prefer config/environment |
| `--instance ID` | | Select an instance returned by discovery |
| `--timeout SEC` | | Operation budget: 5 seconds; client restart: 30 seconds |
| `--output text/json` | | Resource command output format |
| `--no-input` | | Explicitly disable prompts |

Discovery considers configured TCP/TLS/Unix endpoints and, on macOS, the current
user's Clash Verge service socket. Multiple reachable endpoints require an explicit
instance. An explicit controller never falls back to another instance. Windows
named pipes are not implemented; Windows TCP remains supported.

Controller traffic ignores environment proxy variables. Proxy queries only
expose allowlisted summary fields. Profile IDs in the context bind a pipe-produced
request to the same local profile; unknown standalone profiles are represented by null.

### Profiles, host settings and diagnostics

Management operations share the same result envelope and global output option.
Configuration reads include `data.source=configured`; file updates return
`status=pending` when runtime reload has not been verified. Set host switches
explicitly to `on` or `off`, so repeated requests do not invert state.

| Area | Commands |
| --- | --- |
| Profiles | `profile list/show/add/activate/verify/delete`, `profile traffic` |
| System proxy | `host proxy get`, `host proxy set on/off` |
| TUN | `host tun get`, `host tun set on/off` |
| Ports | `host ports get`, `host ports set TYPE PORT [--enable/--disable]` |
| Application | `host restart`, `host open config/logs`, `host webui` |
| Configuration | `config get core/verge`, `config set KEY VALUE`, `config dns/rules/path/refresh` |
| Backups | `backup create [NAME]`, `backup list`, `backup restore NAME` |
| Logs | `logs read --lines N`, `logs search KEYWORD` |
| HTTP health | `health --url URL [--proxy URL]` |

Profile activation restarts the official client and verifies its generated runtime configuration. System proxy, TUN and port
configuration writes still require application through Verge; editing those files
alone does not prove a reload.
`config get` explicitly exports raw configuration and
can include credentials. Profile lists omit subscription URLs.

```bash
clashier --output json profile list
clashier --output json host proxy set on
clashier --output json backup create before-change
clashier --output json health --url https://www.gstatic.com/generate_204 --proxy http://127.0.0.1:7897
```

`health` has no built-in website and makes a direct request unless `--proxy` is
provided. Non-2xx responses and network failures return a structured error.
For a composed workflow, see [select-reachable.sh](examples/select-reachable.sh). Run it with
`bash examples/select-reachable.sh GROUP NODE TEST_URL`; it requires jq.

Use global `--output json` with the resource commands above. The `clashier.py`
source launcher works on every supported platform.

## Development and verification

### Set up the environment and run checks

```bash
uv sync --locked
uv run --locked pytest
uv run --locked pytest tests/integration tests/application tests/contract
uv run --locked ruff check .
uv build --wheel
```

Tests use temporary profiles and disposable local controllers; they do not touch
the user's Clash installation. Unix integration tests run on macOS/Linux.

### Source modules and responsibilities

```text
src/clashier/
  cli/           # resource commands, protocol.py for contracts, render.py for output
  application/   # proxy selection, native profile/selection persistence and dependency interfaces
  adapters/
    mihomo.py            # controller protocol
    transport.py         # TCP and Unix socket clients
    discovery.py         # controller discovery
    verge_store.py       # configured settings, backups and bounded log reads
    profiles.py          # profile catalog and subscription content
    yaml_files.py        # validated YAML and atomic UTF-8 replacement
    web.py               # subscription downloads and explicit URL checks
  models.py      # operation requests and runtime types
  errors.py      # structured operation failures
  bootstrap.py   # dependency composition per invocation
  schemas/       # installed versioned JSON contracts
  platforms.py   # platform paths and application helpers
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution details.

## Related projects

| Project | Focus |
| --- | --- |
| [Hsiifu3/clash-verge-skill](https://github.com/Hsiifu3/clash-verge-skill) | Python standard-library Skill for Clash Verge Rev. Supports Unix sockets on macOS/Linux and HTTP API, proxy groups, node switching, latency tests, and Rule/Global/Direct modes. |
| [Kerry1020/clash-verge-cli](https://github.com/Kerry1020/clash-verge-cli) | CLI for macOS, Windows and Linux, covering nodes, policy groups, subscription profiles, system proxy, TUN and latency tests. Suited to broader command-line management of Clash Verge. |
| [Hanyang-Li/verge-proxy](https://github.com/Hanyang-Li/verge-proxy) | Rust CLI with zsh integration for modes, groups, nodes and proxy environment variables in the current shell. Provides Apple Silicon binaries. |

## License information

Distributed under GPL-3.0. See [LICENSE](LICENSE) for the full terms.
