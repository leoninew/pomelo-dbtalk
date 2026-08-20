"""CLI contract for SQLite/MySQL JSONL data transfer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click

from dbtalk.context import DbtalkContext

from .format import gzip_output_path
from .transfer import (
    DatabaseDriver,
    DatabaseTransferError,
    ExportOptions,
    ImportOptions,
    TransferConnection,
    TransferMode,
    export_database,
    import_database,
    validate_connection,
)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
DEFAULT_EXPORT_OUTPUT_DIRECTORY = "data"


@dataclass(frozen=True)
class ImportCommandArguments:
    """Click-provided import options after conversion to domain input types."""

    target: DatabaseDriver
    input_path: Path
    mode: TransferMode
    sqlite_path: Path | None
    mysql_dsn_env: str | None
    timezone_name: str
    include_tables: tuple[str, ...]
    exclude_tables: tuple[str, ...]


@dataclass(frozen=True)
class ExportCommandArguments:
    """Click-provided export options after conversion to domain input types."""

    source: DatabaseDriver
    output_path: Path | None
    sqlite_path: Path | None
    mysql_dsn_env: str | None
    timezone_name: str
    include_tables: tuple[str, ...]
    exclude_tables: tuple[str, ...]
    archive: bool


def parse_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise click.BadParameter(f"unknown IANA timezone: {value}") from error


def connection_from_options(
    driver: str, sqlite_path: Path | None, mysql_dsn_env: str | None
) -> TransferConnection:
    if driver == "sqlite":
        connection = TransferConnection(
            driver="sqlite",
            sqlite_path=sqlite_path,
            mysql_dsn_env=mysql_dsn_env,
        )
    elif driver == "mysql":
        connection = TransferConnection(
            driver="mysql",
            sqlite_path=sqlite_path,
            mysql_dsn_env=mysql_dsn_env,
        )
    else:
        raise click.UsageError("database driver must be sqlite or mysql")
    try:
        validate_connection(connection)
    except RuntimeError as error:
        raise click.UsageError(str(error)) from error
    return connection


def zero_datetime_as_null_from_context(ctx: click.Context) -> bool:
    """Read the root database-transfer setting, keeping direct command tests usable."""

    root_object = ctx.find_root().obj
    if not isinstance(root_object, DbtalkContext):
        return True
    return root_object.settings.database.zero_datetime_as_null


def default_export_output(
    source: DatabaseDriver,
    now: datetime | None = None,
    *,
    output_directory: str | Path = DEFAULT_EXPORT_OUTPUT_DIRECTORY,
    archive: bool = False,
) -> Path:
    """Create a default export directory and return a timestamped JSONL path."""

    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    directory = Path(output_directory)
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{source}-{timestamp}.jsonl"
    return gzip_output_path(output) if archive else output


def resolve_export_output(
    source: DatabaseDriver,
    requested_output: Path | None,
    *,
    archive: bool,
) -> Path:
    """Resolve an export file, treating only existing directories as directories."""

    if requested_output is None:
        return default_export_output(source, archive=archive)
    if requested_output.is_dir():
        return default_export_output(
            source,
            output_directory=requested_output,
            archive=archive,
        )
    if not requested_output.parent.is_dir():
        raise click.ClickException(
            f"Export output directory does not exist: {requested_output.parent}"
        )
    return gzip_output_path(requested_output) if archive else requested_output


@click.group("database", context_settings=CONTEXT_SETTINGS)
def database() -> None:
    """Transfer SQLite/MySQL table data through JSONL."""


@database.command("export", context_settings=CONTEXT_SETTINGS)
@click.option("--source", type=click.Choice(["sqlite", "mysql"]), required=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="JSONL output file or existing directory. Defaults to data/<source>-<timestamp>.jsonl.",
)
@click.option("--sqlite-path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--mysql-dsn-env", help="Environment variable containing the MySQL DSN.")
@click.option("--tz", "timezone_name", default="UTC", show_default=True)
@click.option(
    "--include-table",
    "include_tables",
    multiple=True,
    help="Limit export to selected tables. Repeat for multiple tables.",
)
@click.option(
    "--exclude-table",
    "exclude_tables",
    multiple=True,
    help="Exclude a table from export. Repeat for multiple tables.",
)
@click.option(
    "--archive",
    "archive",
    is_flag=True,
    help="Write the JSONL export as a gzip file.",
)
@click.pass_context
def export_command(ctx: click.Context, /, **click_options: object) -> None:
    """Export all source table data to one JSONL file."""

    arguments = export_command_arguments(click_options)
    connection = connection_from_options(
        arguments.source,
        arguments.sqlite_path,
        arguments.mysql_dsn_env,
    )
    try:
        output_path = resolve_export_output(
            arguments.source,
            arguments.output_path,
            archive=arguments.archive,
        )
        summary = export_database(
            ExportOptions(
                connection=connection,
                output=output_path,
                timezone=parse_timezone(arguments.timezone_name),
                include_tables=arguments.include_tables,
                exclude_tables=arguments.exclude_tables,
                zero_datetime_as_null=zero_datetime_as_null_from_context(ctx),
            )
        )
    except DatabaseTransferError as error:
        raise click.ClickException(str(error)) from error
    click.echo(
        f"JSONL database export written to {output_path.resolve()} "
        f"({summary.table_count} tables, {summary.row_count} rows)"
    )


def export_command_arguments(options: dict[str, object]) -> ExportCommandArguments:
    """Convert Click's dynamic export options to domain input types."""

    source = options.get("source")
    output_path = options.get("output")
    sqlite_path = options.get("sqlite_path")
    mysql_dsn_env = options.get("mysql_dsn_env")
    timezone_name = options.get("timezone_name")
    include_tables = options.get("include_tables")
    exclude_tables = options.get("exclude_tables")
    archive = options.get("archive")
    if source == "sqlite":
        driver: DatabaseDriver = "sqlite"
    elif source == "mysql":
        driver = "mysql"
    else:
        raise RuntimeError("Click did not provide a valid source driver")
    if output_path is not None and not isinstance(output_path, Path):
        raise RuntimeError("Click did not provide an output path")
    if sqlite_path is not None and not isinstance(sqlite_path, Path):
        raise RuntimeError("Click did not provide a valid SQLite path")
    if mysql_dsn_env is not None and not isinstance(mysql_dsn_env, str):
        raise RuntimeError("Click did not provide a valid MySQL DSN variable")
    if not isinstance(timezone_name, str):
        raise RuntimeError("Click did not provide a valid timezone")
    if not isinstance(include_tables, tuple) or not all(
        isinstance(name, str) for name in include_tables
    ):
        raise RuntimeError("Click did not provide valid included table names")
    if not isinstance(exclude_tables, tuple) or not all(
        isinstance(name, str) for name in exclude_tables
    ):
        raise RuntimeError("Click did not provide valid excluded table names")
    if not isinstance(archive, bool):
        raise RuntimeError("Click did not provide a valid archive option")
    return ExportCommandArguments(
        source=driver,
        output_path=output_path,
        sqlite_path=sqlite_path,
        mysql_dsn_env=mysql_dsn_env,
        timezone_name=timezone_name,
        include_tables=include_tables,
        exclude_tables=exclude_tables,
        archive=archive,
    )


@database.command("import", context_settings=CONTEXT_SETTINGS)
@click.option("--target", type=click.Choice(["sqlite", "mysql"]), required=True)
@click.option(
    "--input",
    "input_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--mode", type=click.Choice(["insert", "upsert"]), required=True)
@click.option("--sqlite-path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--mysql-dsn-env", help="Environment variable containing the MySQL DSN.")
@click.option("--tz", "timezone_name", default="UTC", show_default=True)
@click.option(
    "--include-table",
    "include_tables",
    multiple=True,
    help="Limit import to selected tables. Repeat for multiple tables.",
)
@click.option(
    "--exclude-table",
    "exclude_tables",
    multiple=True,
    help="Exclude a table from import. Repeat for multiple tables.",
)
def import_command(**click_options: object) -> None:
    """Import JSONL table data into an existing target schema."""

    arguments = import_command_arguments(click_options)
    connection = connection_from_options(
        arguments.target,
        arguments.sqlite_path,
        arguments.mysql_dsn_env,
    )
    try:
        summary = import_database(
            ImportOptions(
                connection=connection,
                input=arguments.input_path,
                mode=arguments.mode,
                timezone=parse_timezone(arguments.timezone_name),
                include_tables=arguments.include_tables,
                exclude_tables=arguments.exclude_tables,
            )
        )
    except DatabaseTransferError as error:
        raise click.ClickException(str(error)) from error
    click.echo(
        f"JSONL database import completed ({summary.table_count} tables, {summary.row_count} rows)"
    )


def import_command_arguments(options: dict[str, object]) -> ImportCommandArguments:
    """Convert Click's dynamic option mapping before invoking transfer logic."""

    target = options.get("target")
    input_path = options.get("input_path")
    mode = options.get("mode")
    sqlite_path = options.get("sqlite_path")
    mysql_dsn_env = options.get("mysql_dsn_env")
    timezone_name = options.get("timezone_name")
    include_tables = options.get("include_tables")
    exclude_tables = options.get("exclude_tables")
    if target == "sqlite":
        driver: DatabaseDriver = "sqlite"
    elif target == "mysql":
        driver = "mysql"
    else:
        raise RuntimeError("Click did not provide a valid target driver")
    if not isinstance(input_path, Path):
        raise RuntimeError("Click did not provide an input path")
    if mode == "insert":
        transfer_mode: TransferMode = "insert"
    elif mode == "upsert":
        transfer_mode = "upsert"
    else:
        raise RuntimeError("Click did not provide a valid import mode")
    if sqlite_path is not None and not isinstance(sqlite_path, Path):
        raise RuntimeError("Click did not provide a valid SQLite path")
    if mysql_dsn_env is not None and not isinstance(mysql_dsn_env, str):
        raise RuntimeError("Click did not provide a valid MySQL DSN variable")
    if not isinstance(timezone_name, str):
        raise RuntimeError("Click did not provide a valid timezone")
    if not isinstance(include_tables, tuple) or not all(
        isinstance(name, str) for name in include_tables
    ):
        raise RuntimeError("Click did not provide valid included table names")
    if not isinstance(exclude_tables, tuple) or not all(
        isinstance(name, str) for name in exclude_tables
    ):
        raise RuntimeError("Click did not provide valid excluded table names")
    return ImportCommandArguments(
        target=driver,
        input_path=input_path,
        mode=transfer_mode,
        sqlite_path=sqlite_path,
        mysql_dsn_env=mysql_dsn_env,
        timezone_name=timezone_name,
        include_tables=include_tables,
        exclude_tables=exclude_tables,
    )
