"""Compose resource commands and adapt failures to a stable CLI protocol."""

import sys
from typing import List, Optional

import click
import yaml

from clashier import __version__
from clashier.bootstrap import Bootstrap
from clashier.cli.backup import backup
from clashier.cli.config import config
from clashier.cli.core import capabilities, core, schema, status
from clashier.cli.diagnostics import health, logs
from clashier.cli.host import host
from clashier.cli.profile import profile
from clashier.cli.proxy import proxy
from clashier.cli.render import configure_console, emit_error
from clashier.cli.wizard import choose
from clashier.errors import OperationError


class ProtocolGroup(click.Group):
    """Handle errors once, including usage failures before callbacks run."""

    def main(self, args=None, prog_name=None, standalone_mode=True, **extra):
        args = list(sys.argv[1:] if args is None else args)
        json_mode = _json_requested(args)
        ctx = None
        code = 0
        try:
            with self.make_context(prog_name or "clashier", args, **extra) as ctx:
                return self.invoke(ctx)
        except click.exceptions.Exit as exc:
            code = exc.exit_code
        except click.ClickException as exc:
            if not standalone_mode:
                raise
            emit_error(OperationError("INVALID_ARGUMENT", exc.format_message()),
                       ctx.obj if ctx else None, json_mode)
            code = exc.exit_code
        except OperationError as exc:
            if not standalone_mode:
                raise
            emit_error(exc, ctx.obj if ctx else None, json_mode)
            code = 1
        except (OSError, yaml.YAMLError) as exc:
            emit_error(OperationError("CONFIGURATION_ERROR", "Cannot read or write configuration ({})".format(
                type(exc).__name__)), ctx.obj if ctx else None, json_mode)
            code = 1
        except ValueError:
            emit_error(OperationError("INVALID_ARGUMENT", "Invalid controller address or configuration value"),
                       ctx.obj if ctx else None, json_mode)
            code = 2
        except (KeyboardInterrupt, click.Abort):
            click.echo("Interrupted", err=True)
            code = 130
        if standalone_mode:
            raise SystemExit(code)
        return code


def _json_requested(args: List[str]) -> bool:
    for index, item in enumerate(args):
        if item == "--output=json" or (item == "--output" and args[index + 1:index + 2] == ["json"]):
            return True
    return False


@click.group(cls=ProtocolGroup, invoke_without_command=True,
             context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config-dir", envvar="CLASH_VERGE_DIR", type=click.Path(file_okay=False))
@click.option("--controller", envvar="CLASH_API_URL", help="HTTP(S) address or unix:///absolute/socket.")
@click.option("--secret", envvar="CLASH_API_SECRET", help="Controller secret (prefer environment/config).")
@click.option("--timeout", default=None, type=click.FloatRange(min=0.1),
              help="Operation budget in seconds (default: 5; client restart: 30).")
@click.option("--instance", help="Exact instance ID returned by core discover.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
@click.option("--no-input", is_flag=True, help="Disable prompts, including the optional choose command.")
@click.version_option(__version__, "-V", "--version", prog_name="clashier")
@click.pass_context
def clashier(ctx: click.Context, config_dir: Optional[str], controller: Optional[str], secret: Optional[str],
        timeout: Optional[float], instance: Optional[str], output: str, no_input: bool) -> None:
    """Clashier: composable proxy operations for shells and agents."""
    ctx.obj = Bootstrap(config_dir, controller, secret, timeout, instance, output, no_input)
    ctx.call_on_close(ctx.obj.close)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


for _command in (proxy, core, capabilities, schema, status, profile, host, backup, config, logs, health, choose):
    clashier.add_command(_command)


def main(argv: Optional[List[str]] = None, prog_name: Optional[str] = None) -> None:
    """Installed entry point, also used by the source launchers."""
    configure_console()
    clashier.main(args=argv, prog_name=prog_name)
