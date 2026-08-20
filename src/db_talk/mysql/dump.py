from __future__ import annotations

import contextlib
import shlex
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import click

from db_talk.settings import MySQLDumpConfig

from .client import (
    docker_database_host,
    docker_host_gateway_args,
    docker_mysql_image,
    ensure_command_succeeded,
    gzip_output_path,
    is_local_mysql_host,
    mysql_connection_args,
    mysql_password_environment,
    remove_temporary_container,
    run_command,
    write_gzip,
)

DOCKER_DUMP_PATH = "/tmp/dbtalk-dump.sql"


@dataclass(frozen=True)
class MysqlDumpOptions:
    host: str
    port: int
    user: str
    password: str
    database: str
    output: Path
    create_database: bool = False
    drop_database: bool = False
    archive: bool = False


@dataclass(frozen=True)
class MysqlDumpOverrides:
    host: str | None
    port: int | None
    user: str | None
    password: str | None
    database: str | None
    output: Path | None
    create_database: bool | None
    drop_database: bool | None
    archive: bool = False


def mysqldump_command_args(
    options: MysqlDumpOptions, output: Path | str, *, compress: bool | None = None
) -> list[str]:
    """Build a mysqldump command vector without a password environment value."""
    args = ["mysqldump"]
    if compress is None:
        compress = not is_local_mysql_host(options.host)
    if compress:
        args.append("-C")
    args.extend(
        [
            *mysql_connection_args(options.host, options.port, options.user),
            "-B",
            options.database,
        ]
    )
    if options.drop_database:
        args.append("--add-drop-database")
    if not options.create_database:
        args.append("--no-create-db")
    args.extend(
        [
            "-R",
            "-E",
            "--set-gtid-purged=OFF",
            "--skip-lock-tables",
            "-r",
            str(output),
        ]
    )
    return args


def mysqldump_args(options: MysqlDumpOptions) -> list[str]:
    """Build the mysqldump argument vector without executing it."""
    return [
        "env",
        f"MYSQL_PWD={options.password}",
        *mysqldump_command_args(options, options.output),
    ]


def generate_dump_command(options: MysqlDumpOptions) -> str:
    """Return a shell-safe mysqldump command for the supplied options."""
    return shlex.join(mysqldump_args(options))


def default_dump_output(
    database: str,
    now: datetime | None = None,
    *,
    output_directory: str | Path,
    archive: bool = False,
) -> Path:
    """Create the configured dump directory and return a timestamped path."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    directory = Path(output_directory)
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{database}-{timestamp}.sql"
    return gzip_output_path(output) if archive else output


def resolve_dump_options(
    config: MySQLDumpConfig,
    overrides: MysqlDumpOverrides,
) -> MysqlDumpOptions:
    host = overrides.host if overrides.host is not None else config.host
    port = overrides.port if overrides.port is not None else config.port
    user = overrides.user if overrides.user is not None else config.user
    password = overrides.password if overrides.password is not None else config.password
    database = overrides.database if overrides.database is not None else config.database
    missing = [
        name
        for name, value in (
            ("user", user),
            ("password", password),
            ("database", database),
        )
        if not value
    ]
    if missing:
        names = ", ".join(missing)
        raise click.ClickException(
            f"Missing mysqldump configuration: {names}. "
            "Set mysqldump values or pass the corresponding CLI options."
        )

    return MysqlDumpOptions(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        output=(
            default_dump_output(
                database,
                output_directory=(
                    overrides.output if overrides.output is not None else config.output_directory
                ),
                archive=overrides.archive,
            )
            if overrides.output is None or overrides.output.is_dir()
            else overrides.output
        ),
        create_database=(
            overrides.create_database
            if overrides.create_database is not None
            else config.create_database
        ),
        drop_database=(
            overrides.drop_database if overrides.drop_database is not None else config.drop_database
        ),
        archive=overrides.archive,
    )


def dump_database(options: MysqlDumpOptions) -> Path:
    """Export a database with a local client or a local Docker MySQL image."""
    output = options.output.resolve()
    if not output.parent.is_dir():
        raise click.ClickException(f"Dump output directory does not exist: {output.parent}")

    if not options.archive:
        dump_database_file(options, output)
        return output

    archive_output = gzip_output_path(output)
    temporary_output = output.parent / f".dbtalk-mysqldump-{uuid.uuid4().hex}.sql"
    try:
        dump_database_file(options, temporary_output)
        write_gzip(temporary_output, archive_output)
    finally:
        with contextlib.suppress(OSError):
            temporary_output.unlink()
    return archive_output


def dump_database_file(options: MysqlDumpOptions, output: Path) -> None:
    """Write an uncompressed SQL dump to the supplied path."""
    if shutil.which("mysqldump") is not None:
        dump_with_local_client(options, output)
        return

    image, reason = docker_mysql_image()
    if image is None:
        raise click.ClickException(f"mysqldump is not available. {reason}")

    dump_with_docker(options, output, image)


def dump_with_local_client(options: MysqlDumpOptions, output: Path) -> None:
    result = run_command(
        mysqldump_command_args(options, output),
        mysql_password_environment(options.password),
    )
    ensure_command_succeeded(result, "mysqldump")


def dump_with_docker(options: MysqlDumpOptions, output: Path, image: str) -> None:
    """Run mysqldump in a temporary container and copy the result to the host."""
    container_name = f"dbtalk-mysqldump-{uuid.uuid4().hex}"
    container_options = MysqlDumpOptions(
        host=docker_database_host(options.host),
        port=options.port,
        user=options.user,
        password=options.password,
        database=options.database,
        output=Path(DOCKER_DUMP_PATH),
        create_database=options.create_database,
        drop_database=options.drop_database,
    )
    command = ["docker", "run", "--name", container_name]
    command.extend(docker_host_gateway_args(options.host))
    command.extend(
        [
            "--env",
            "MYSQL_PWD",
            "--entrypoint",
            "mysqldump",
            image,
            *mysqldump_command_args(
                container_options,
                DOCKER_DUMP_PATH,
                compress=not is_local_mysql_host(options.host),
            )[1:],
        ]
    )
    environment = mysql_password_environment(options.password)

    try:
        ensure_command_succeeded(run_command(command, environment), "Docker mysqldump")
        copy_command = [
            "docker",
            "cp",
            f"{container_name}:{DOCKER_DUMP_PATH}",
            str(output),
        ]
        ensure_command_succeeded(run_command(copy_command, environment), "Docker dump copy")
    finally:
        remove_temporary_container(container_name, environment)
