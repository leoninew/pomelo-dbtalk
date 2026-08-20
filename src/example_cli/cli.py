"""Click root command and process lifecycle."""

from __future__ import annotations

import click

from example_cli import __version__
from example_cli.commands import greet, status
from example_cli.context import AppContext
from example_cli.logging_config import configure_logging
from example_cli.settings import load_settings

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="example-cli")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug log messages.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Run the example Click CLI."""
    settings = load_settings()
    configure_logging(
        settings.logging.level,
        settings.logging.format,
        verbose,
    )
    ctx.obj = AppContext(settings=settings, verbose=verbose)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(greet)
cli.add_command(status)


def main() -> None:
    """Invoke the command-line application."""
    cli()
