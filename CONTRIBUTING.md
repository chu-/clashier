# Contributing

For end-user setup, see [installation](docs/install.md). Command contracts and
structured results are described in [Agent usage](docs/agent-usage.md).

## Setup

```bash
uv sync --locked
uv run --locked clashier --help
```

Dependencies are declared in `pyproject.toml`, with pytest and ruff in the `dev`
dependency group. Update `uv.lock` explicitly when changing dependencies; keep
ordinary runs locked.

## Checks

```bash
uv run --locked pytest
uv run --locked ruff check .
uv build --wheel
```

The test suite uses temporary configuration and disposable local TCP/Unix socket
controllers. It runs without a Clash Verge installation or external website access.

## Try the installed command

```bash
uv tool install .
uv tool run clashier --version
uv tool run clashier --output json capabilities
uv tool run clashier --output json schema show proxy.list
```

The source launcher is available after `uv sync --locked`:

```bash
uv run --locked python clashier.py --help
uv run --locked python -m clashier --help
```

When changing command behavior or JSON results, update both READMEs,
`docs/agent-usage.md` and `skills/clashier/SKILL.md` together. Update
`docs/install.md` when installation or host integration changes. Check CLI
installation, Skill discovery and controller connectivity separately.

Changes are licensed under GPL-3.0; see [LICENSE](LICENSE).
