"""Click root command and process lifecycle."""

from __future__ import annotations

import click

from dbtalk import __version__
from dbtalk.commands import database, mysql, postgres
from dbtalk.context import DbtalkContext
from dbtalk.logging_config import configure_logging
from dbtalk.settings import load_settings

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="dbtalk")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug log messages.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Run database backup, restore, transfer, query, and execution operations."""
    settings = load_settings()
    configure_logging(
        settings.logging.level,
        settings.logging.format,
        verbose or settings.verbose,
    )
    ctx.obj = DbtalkContext(settings=settings, verbose=verbose or settings.verbose)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(mysql)
cli.add_command(postgres)
cli.add_command(database)


def main() -> None:
    """Invoke the command-line application."""
    cli()
