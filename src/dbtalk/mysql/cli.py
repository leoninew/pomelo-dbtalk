from __future__ import annotations

from pathlib import Path

import click

from dbtalk.context import dbtalk_context
from dbtalk.database.dsn import dsn_from_environment, parse_dsn
from dbtalk.database.models import DatabaseOperationError
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
@click.option("--dsn", "dsn_value", help="Complete MySQL SQLAlchemy-style DSN.")
@click.option("--dsn-env", help="Environment variable containing the MySQL DSN.")
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
    dsn_value: str | None,
    dsn_env: str | None,
    output: Path | None,
    create_database: bool | None,
    drop_database: bool | None,
    archive: bool,
) -> None:
    """Export a MySQL database."""
    settings = context_settings(ctx)
    host, port, user, password, database = mysql_connection_from_dsn(dsn_value, dsn_env)
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
@click.option("--dsn", "dsn_value", help="Complete MySQL SQLAlchemy-style DSN.")
@click.option("--dsn-env", help="Environment variable containing the MySQL DSN.")
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="SQL dump input path.",
)
@click.pass_context
def restore_command(  # noqa: PLR0913 - Click passes one argument for each CLI option.
    ctx: click.Context,
    dsn_value: str | None,
    dsn_env: str | None,
    input: Path,
) -> None:
    """Import a MySQL dump."""
    settings = context_settings(ctx)
    host, port, user, password, database = mysql_connection_from_dsn(dsn_value, dsn_env)
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


def mysql_connection_from_dsn(
    dsn: str | None,
    dsn_env: str | None,
) -> tuple[str, int, str, str, str]:
    """Resolve one explicit MySQL DSN into native client connection fields."""

    if (dsn is None) == (dsn_env is None):
        raise click.UsageError("provide exactly one of --dsn or --dsn-env")
    try:
        parsed = parse_dsn(dsn) if dsn is not None else dsn_from_environment(dsn_env)
    except DatabaseOperationError as error:
        raise click.UsageError(str(error)) from error
    if parsed.dialect != "mysql":
        raise click.UsageError("MySQL dump and restore require a mysql+pymysql DSN")
    host = parsed.host
    user = parsed.url.username
    database = parsed.database
    if not host or not user or not database:
        raise click.UsageError("MySQL DSN must include host, user, and database")
    return host, parsed.port or 3306, user, parsed.url.password or "", database
