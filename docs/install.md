# Install Clashier

Source repository: <https://github.com/chu-/clashier>.
These steps apply to macOS, Linux and Windows. An installation Agent should
complete the CLI checks, install the Skill when requested, attempt the controller
check, and report those results separately. Installation uses read-only checks;
profile activation and node changes belong to a subsequent requested task.

The README is the installation entry point. The executable is installed with uv;
the Skill entry is `skills/clashier/SKILL.md` and is copied into the Agent host's
discovery directory. Each component can be installed independently.

## Prerequisites

- Run on the computer whose Clash Verge / mihomo instance you intend to control,
  or supply an explicitly reachable remote controller for runtime queries and
  runtime-only selection. Profile activation and persistent selection require
  the official desktop client and its native configuration directory locally.
- Check `uv --version` and `git --version`. Git is required for Git URL installation.
- Clashier supports Python 3.8+. Add `--python 3.12` to the installation command
  to let uv select or download that interpreter when needed.
- Profile scripts use an embedded V8 wheel installed with the CLI, without Node.js.
  Wheels cover macOS Intel/Apple Silicon, Windows x64, and Linux x64/ARM64 with
  glibc 2.31+ or musl 1.2+.

If uv is missing, use its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
The standalone commands are:

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

If the current process cannot find the newly installed uv, use the executable
path printed by the installer. With the default location this is
`$HOME/.local/bin/uv` on macOS/Linux or `$HOME\.local\bin\uv.exe` on Windows.
Install missing Git using the platform's normal package manager or
[Git downloads](https://git-scm.com/downloads).

## Install from GitHub

The source must already be published and readable by the installing Agent. Check:

```bash
git ls-remote https://github.com/chu-/clashier.git HEAD
```

A usable repository returns a commit SHA and `HEAD`. A 404, access error or empty
repository is a source-access problem; use an accessible revision or a complete
local checkout. Do not report a remote installation as complete without obtaining
the source.

The following works in a POSIX shell and PowerShell, from any directory:

```bash
uv tool install 'git+https://github.com/chu-/clashier.git'
```

This installs an isolated CLI environment and its runtime dependencies. No clone,
environment activation or development dependencies are needed.
Use this Git URL rather than assuming a package with the same name is available
from a package index.

For a user-specified version, append an existing tag or full commit SHA to the
Git URL: `git+https://github.com/chu-/clashier.git@REF`, replacing `REF` with the
requested revision. Obtain valid refs with:

```bash
git ls-remote --tags https://github.com/chu-/clashier.git
```

Without a revision, installation uses the repository's default branch.
Keep the chosen revision in the installation report when a pinned source is used.

## Install from a local checkout

For an unpublished checkout, or a copy already supplied by the user, replace the
example path with that complete source directory:

```bash
uv tool install --reinstall /path/to/clashier
```

Quote paths containing spaces. This installs the CLI from local source; copying
only the README or Skill file does not supply the Python package. Continue with
the checks below and, when requested, copy the Skill from the same checkout.

## Locate and verify the command

```bash
clashier --version
clashier --output json capabilities
clashier --output json schema show proxy.select
clashier --output json schema show proxy.list
```

All four checks should exit 0. The resource checks return JSON with `ok: true` and
`schema_version: "1"`. They do not require a running proxy controller.

If `clashier` is not found, get its directory with `uv tool dir --bin` and invoke
the executable there. This also handles Agent sessions whose PATH has not refreshed.

macOS / Linux:

```bash
clashier_bin="$(uv tool dir --bin)/clashier"
"$clashier_bin" --version
"$clashier_bin" --output json capabilities
```

Windows PowerShell:

```powershell
$clashierBin = Join-Path (uv tool dir --bin) 'clashier.exe'
& $clashierBin --version
& $clashierBin --output json capabilities
```

For future shells, `uv tool update-shell` configures the tools directory on PATH.
Direct invocation works immediately; reopening the terminal is another option.

## Check the controller separately

```bash
clashier --output json core discover
```

`ok: true` with at least one `data.items` entry confirms controller connectivity.
Save its `instance_id` when an operation needs an explicit instance.
If discovery fails but the package checks passed, report **installed; controller
unavailable** with `error.code`. A controller failure does not require reinstalling
the CLI. Check that Clash Verge / mihomo is running and that its controller is enabled.

For an explicit controller:

```bash
clashier --output json --controller http://127.0.0.1:9097 core discover
```

The address above is illustrative; use the configured address. Supply an existing
config directory through `--config-dir`, or use `CLASH_VERGE_DIR`, `CLASH_API_URL`
and `CLASH_API_SECRET` as documented in the README. Keep secrets out of installation
reports. Windows currently requires a TCP controller; named pipes are unsupported.

Completion report:

- Installed CLI version and executable path.
- Source URL and revision, if pinned.
- Package checks: pass/fail.
- Controller check: reachable/unavailable/unsupported, with an error code if present.
- Optional Skill location, only if installed.

## Optional Agent Skill

The CLI works without a Skill. When both are requested, use one checkout for the
CLI and Skill so their command contracts match. In a fresh working directory:

```bash
git clone https://github.com/chu-/clashier.git clashier-source
uv tool install --reinstall ./clashier-source
```

For a supplied checkout, use its path instead of cloning. For a requested revision,
check it out before installing either component. Record the checkout's commit SHA
when available; identify an unpublished working copy as local source.

| Host | User scope | Project scope |
| --- | --- | --- |
| Codex | `~/.agents/skills/clashier/` | `.agents/skills/clashier/` |
| Claude Code | `~/.claude/skills/clashier/` | `.claude/skills/clashier/` |

Use the home directory of the Agent's actual user on Windows as well. Project
scope refers to the project where the Agent will use Clashier, which can differ
from the Clashier source checkout.

For a **new user-level Codex destination**, copy the complete Skill directory:

```bash
uv run --no-project --python 3.12 python -c "from pathlib import Path; from shutil import copytree; copytree('clashier-source/skills/clashier', Path.home() / '.agents/skills/clashier')"
```

For a **new user-level Claude Code destination**, use this instead:

```bash
uv run --no-project --python 3.12 python -c "from pathlib import Path; from shutil import copytree; copytree('clashier-source/skills/clashier', Path.home() / '.claude/skills/clashier')"
```

These commands work in POSIX shells and PowerShell. Change the source path for a
supplied checkout. They stop if the destination already exists; inspect and preserve
local customizations before updating that installed Skill. For project scope, use
the intended target workspace's path from the table, not the temporary source clone.

Codex users can alternatively ask `$skill-installer` to install
`https://github.com/chu-/clashier/tree/main/skills/clashier`; the CLI still needs its
separate installation. Use the actual path reported by the host installer.

Verify `SKILL.md` exists at the destination and check the host's Skill selector
(`$clashier` or `/skills` in Codex CLI). Codex detects newly installed local Skills;
if discovery does not refresh, restart the host. Report **copied** separately from
**discovered** when the current session cannot verify host discovery.

See [Codex Skills](https://learn.chatgpt.com/docs/build-skills) and
[Claude Code Skills](https://code.claude.com/docs/en/skills) for host discovery details.
Hosted Agents need access to the target controller from their execution environment;
copying a local Skill alone does not provide that access.

## Update and uninstall

For a default-branch installation:

```bash
uv tool upgrade clashier
```

To switch to a specific source revision, repeat `uv tool install --reinstall`
with the Git URL and selected `@REF`. Repeat the package and controller checks
after updating. Update a copied Skill from the same revision when applicable.

Uninstall the CLI:

```bash
uv tool uninstall clashier
```

This leaves Clash Verge configuration and copied Skills in place. Remove only
the installed `clashier` Skill directory if that optional integration is no longer needed.

## Troubleshooting

| Symptom | Next action |
| --- | --- |
| Git URL returns 404 or has no HEAD | Check publication and read access; use a supplied complete local checkout if available |
| `uv` / `git` not found | Install the prerequisite or use its actual executable path |
| Python is unavailable | Add `--python 3.12` to the uv installation command |
| `clashier` not found after installation | Use the executable under `uv tool dir --bin` |
| An unrelated executable already occupies the command name | Inspect the reported path and installed tool before choosing a replacement |
| Dependency download fails | Check package-index/network access; retain the installation error |
| Package checks pass, discovery fails | Check the controller/configuration and the returned error code |
| CLI works but Skill is absent | Copy the Skill into the host's discovery directory and verify host discovery separately |
| Skill is visible but `clashier` is missing | Install the CLI as well; the Skill is a workflow, not the Python runtime |

For command execution and error recovery, read [Agent usage](agent-usage.md).
