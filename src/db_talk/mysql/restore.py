from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import click

from db_talk.settings import MySQLRestoreConfig

from .client import (
    docker_database_host,
    docker_host_gateway_args,
    docker_mysql_image,
    ensure_command_succeeded,
    mysql_connection_args,
    mysql_password_environment,
    remove_temporary_container,
    run_command,
    unpack_gzip_input,
)

MYSQL_USE_STATEMENT = re.compile(
    rb"^USE\s+(?:`(?:``|[^`])+`|[A-Za-z0-9_$]+)\s*;\s*$", re.IGNORECASE
)
MYSQL_DATABASE_DDL_STATEMENT = re.compile(rb"^(?:CREATE|DROP)\s+DATABASE\b", re.IGNORECASE)


@dataclass(frozen=True)
class MysqlRestoreOptions:
    host: str
    port: int
    user: str
    password: str
    input: Path
    database: str | None = None


@dataclass(frozen=True)
class MysqlRestoreOverrides:
    host: str | None
    port: int | None
    user: str | None
    password: str | None
    input: Path
    database: str | None


def mysql_restore_command_args(options: MysqlRestoreOptions) -> list[str]:
    """Build mysql restore arguments without password or input redirection."""
    args = [
        "mysql",
        *mysql_connection_args(options.host, options.port, options.user),
    ]
    if options.database:
        args.extend(["--database", options.database])
    return args


def mysql_restore_args(options: MysqlRestoreOptions) -> list[str]:
    """Build the mysql restore argument vector without input redirection."""
    return [
        "env",
        f"MYSQL_PWD={options.password}",
        *mysql_restore_command_args(options),
    ]


def generate_restore_command(options: MysqlRestoreOptions) -> str:
    """Return a shell-safe mysql restore command for the supplied options."""
    command = shlex.join(mysql_restore_args(options))
    return f"{command} < {shlex.quote(str(options.input))}"


def resolve_restore_options(
    config: MySQLRestoreConfig,
    overrides: MysqlRestoreOverrides,
) -> MysqlRestoreOptions:
    host = overrides.host if overrides.host is not None else config.host
    port = overrides.port if overrides.port is not None else config.port
    user = overrides.user if overrides.user is not None else config.user
    password = overrides.password if overrides.password is not None else config.password
    database = overrides.database if overrides.database is not None else config.database
    missing = [name for name, value in (("user", user), ("password", password)) if not value]
    if missing:
        names = ", ".join(missing)
        raise click.ClickException(
            f"Missing mysqlrestore configuration: {names}. "
            "Set mysqlrestore values or pass the corresponding CLI options."
        )

    return MysqlRestoreOptions(
        host=host,
        port=port,
        user=user,
        password=password,
        input=overrides.input,
        database=database or None,
    )


def restore_database(options: MysqlRestoreOptions) -> Path:
    """Import a SQL dump with a local mysql client or Docker MySQL image."""
    input_path = options.input.resolve()
    if not input_path.is_file():
        raise click.ClickException(f"SQL dump input file does not exist: {input_path}")

    with unpack_gzip_input(input_path, ".sql") as extracted_input:
        rebased_input = (
            rebase_dump_input(extracted_input, options.database) if options.database else None
        )
        restore_input = rebased_input or extracted_input
        try:
            if shutil.which("mysql") is not None:
                restore_with_local_client(options, restore_input)
                return input_path

            image, reason = docker_mysql_image()
            if image is None:
                raise click.ClickException(f"mysql is not available. {reason}")

            restore_with_docker(options, restore_input, image)
            return input_path
        finally:
            if rebased_input is not None:
                with contextlib.suppress(OSError):
                    rebased_input.unlink()


def rebase_dump_input(input_path: Path, database: str) -> Path | None:
    """Return a temporary dump redirected to an existing target database."""
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix="dbtalk-mysql-restore-", suffix=".sql"
    )
    temporary_path = Path(temporary_name)
    replacement = f"USE `{database.replace('`', '``')}`;".encode()
    replaced = False

    try:
        with (
            os.fdopen(file_descriptor, "wb") as destination,
            input_path.open("rb") as source,
        ):
            for line in source:
                line_ending = (
                    b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
                )
                statement = line.removesuffix(b"\r\n").removesuffix(b"\n")
                if MYSQL_DATABASE_DDL_STATEMENT.match(statement):
                    replaced = True
                elif MYSQL_USE_STATEMENT.fullmatch(statement):
                    destination.write(replacement + line_ending)
                    replaced = True
                else:
                    destination.write(line)
    except OSError as error:
        with contextlib.suppress(OSError):
            temporary_path.unlink()
        raise click.ClickException(
            f"Could not prepare SQL dump for target database: {error}"
        ) from error

    if replaced:
        return temporary_path

    temporary_path.unlink()
    return None


def restore_with_local_client(options: MysqlRestoreOptions, input_path: Path) -> None:
    result = run_command(
        mysql_restore_command_args(options),
        mysql_password_environment(options.password),
        input_path=input_path,
    )
    ensure_command_succeeded(result, "mysql restore")


def restore_with_docker(options: MysqlRestoreOptions, input_path: Path, image: str) -> None:
    """Stream a SQL dump into a temporary Docker MySQL client container."""
    container_name = f"dbtalk-mysql-restore-{uuid.uuid4().hex}"
    container_options = MysqlRestoreOptions(
        host=docker_database_host(options.host),
        port=options.port,
        user=options.user,
        password=options.password,
        input=input_path,
        database=options.database,
    )
    command = ["docker", "run", "-i", "--name", container_name]
    command.extend(docker_host_gateway_args(options.host))
    command.extend(
        [
            "--env",
            "MYSQL_PWD",
            "--entrypoint",
            "mysql",
            image,
            *mysql_restore_command_args(container_options)[1:],
        ]
    )
    environment = mysql_password_environment(options.password)

    try:
        result = run_command(command, environment, input_path=input_path)
        ensure_command_succeeded(result, "Docker mysql restore")
    finally:
        remove_temporary_container(container_name, environment)
