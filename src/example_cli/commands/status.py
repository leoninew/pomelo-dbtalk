"""Configuration status example command."""

import logging

import click

from example_cli.context import app_context

logger = logging.getLogger(__name__)


@click.command()
@click.option("--details", is_flag=True, help="Show runtime details.")
@click.pass_context
def status(ctx: click.Context, details: bool) -> None:
    """Show application configuration status."""
    context = app_context(ctx)
    settings = context.settings
    logger.debug("rendering status for %s", settings.app.name)
    click.echo(f"app: {settings.app.name}")
    if details:
        click.echo(f"log_level: {settings.logging.level}")
