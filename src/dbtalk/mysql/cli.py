from __future__ import annotations

from pathlib import Path

import click

from dbtalk.context import dbtalk_context
from dbtalk.settings import Settings

from .client import mysql_client_args, mysql_connection_args
from .dump import (
    MysqlDumpOptions,
    MysqlDumpOverrides,
    default_dump_output,
    dump_database,
    generate_dump_command,
    mysqldump_args,
    resolve_dump_options,
)
from .restore import (
    MysqlRestoreOptions,
    MysqlRestoreOverrides,
    generate_restore_command,
    mysql_restore_args,
    resolve_restore_options,
    restore_database,
)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

__all__ = [
    "MysqlDumpOptions",
    "MysqlDumpOverrides",
    "MysqlRestoreOptions",
    "MysqlRestoreOverrides",
    "default_dump_output",
    "dump_database",
    "generate_dump_command",
    "generate_restore_command",
    "mysql",
    "mysql_client_args",
    "mysql_connection_args",
    "mysql_restore_args",
    "mysqldump_args",
    "resolve_dump_options",
    "resolve_restore_options",
    "restore_database",
]


@click.group("mysql", context_settings=CONTEXT_SETTINGS)
def mysql() -> None:
    """Run MySQL dump and restore operations."""


@mysql.command("dump", context_settings=CONTEXT_SETTINGS)
@click.option("--host", help="MySQL host. Defaults to mysqldump.host.")
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    help="MySQL port. Defaults to mysqldump.port.",
)
@click.option("--user", help="MySQL user. Defaults to mysqldump.user.")
@click.option("--password", help="MySQL password. Defaults to mysqldump.password.")
@click.option("--database", help="Database to export. Defaults to mysqldump.database.")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help=(
        "SQL dump output file or existing directory. Defaults to a timestamped file "
        "in mysqldump.output_directory."
    ),
)
@click.option(
    "--create-database/--no-create-database",
    default=None,
    help="Include CREATE DATABASE statements. Defaults to mysqldump.create_database.",
)
@click.option(
    "--drop-database/--no-drop-database",
    default=None,
    help="Include DROP DATABASE statements. Defaults to mysqldump.drop_database.",
)
@click.option(
    "--archive",
    "archive",
    is_flag=True,
    help="Write the SQL dump as a gzip file.",
)
@click.pass_context
def dump_command(  # noqa: PLR0913 - Click passes one argument for each CLI option.
    ctx: click.Context,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
    database: str | None,
    output: Path | None,
    create_database: bool | None,
    drop_database: bool | None,
    archive: bool,
) -> None:
    """Export a MySQL database."""
    settings = context_settings(ctx)
    options = resolve_dump_options(
        settings.mysqldump,
        MysqlDumpOverrides(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            output=output,
            create_database=create_database,
            drop_database=drop_database,
            archive=archive,
        ),
    )
    completed_output = dump_database(options)
    click.echo(f"MySQL dump written to {completed_output}")


@mysql.command("restore", context_settings=CONTEXT_SETTINGS)
@click.option("--host", help="MySQL host. Defaults to mysqlrestore.host.")
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    help="MySQL port. Defaults to mysqlrestore.port.",
)
@click.option("--user", help="MySQL user. Defaults to mysqlrestore.user.")
@click.option(
    "--password",
    help="MySQL password. Defaults to mysqlrestore.password.",
)
@click.option(
    "--database",
    help="Target database. Defaults to mysqlrestore.database.",
)
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SQL dump input path.",
)
@click.pass_context
def restore_command(  # noqa: PLR0913 - Click passes one argument for each CLI option.
    ctx: click.Context,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
    database: str | None,
    input: Path,
) -> None:
    """Import a MySQL dump."""
    settings = context_settings(ctx)
    options = resolve_restore_options(
        settings.mysqlrestore,
        MysqlRestoreOverrides(
            host=host,
            port=port,
            user=user,
            password=password,
            input=input,
            database=database,
        ),
    )
    restored_input = restore_database(options)
    click.echo(f"MySQL dump restored from {restored_input}")


def context_settings(ctx: click.Context) -> Settings:
    return dbtalk_context(ctx).settings
