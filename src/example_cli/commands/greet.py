"""Greeting example command."""

import click

from example_cli.context import app_context


@click.command()
@click.option("--name", default="world", show_default=True, help="Name to greet.")
@click.pass_context
def greet(ctx: click.Context, name: str) -> None:
    """Print a greeting using the configured prefix."""
    settings = app_context(ctx).settings
    click.echo(f"{settings.app.greeting_prefix}, {name}!")
