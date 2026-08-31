"""PostgreSQL custom archive restore execution."""

from __future__ import annotations

import contextlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath

import click

from .client import (
    PostgresConnection,
    docker_bind_mount,
    docker_database_host,
    docker_host_gateway_args,
    docker_mapped_postgres_container,
    docker_password_environment,
    docker_postgres_image,
    ensure_command_succeeded,
    pgpass_environment,
    run_command,
)


@dataclass(frozen=True)
class PostgresRestoreOptions:
    connection: PostgresConnection
    input: Path
    client_image: str
    clean: bool = False
    if_exists: bool = False
    preserve_owner: bool = False
    preserve_privileges: bool = False
    jobs: int | None = None


def pg_restore_command_args(
    options: PostgresRestoreOptions,
    input_path: PurePath,
    *,
    docker: bool = False,
    mapped_container: bool = False,
) -> list[str]:
    """Build a password-free ``pg_restore`` command vector."""

    host: str | None
    if mapped_container:
        host = ""
    else:
        host = docker_database_host(options.connection.host) if docker else None
    args = [
        "pg_restore",
        "--dbname",
        options.connection.libpq_uri(host=host, socket=mapped_container),
        "--exit-on-error",
    ]
    if options.clean:
        args.append("--clean")
    if options.if_exists:
        args.append("--if-exists")
    if not options.preserve_owner:
        args.append("--no-owner")
    if not options.preserve_privileges:
        args.append("--no-privileges")
    if options.jobs is not None:
        args.extend(["--jobs", str(options.jobs)])
    args.append(str(input_path))
    return args


def restore_database(options: PostgresRestoreOptions) -> Path:
    """Validate and restore one PostgreSQL custom archive."""

    if options.if_exists and not options.clean:
        raise click.ClickException("--if-exists requires --clean")
    input_path = options.input.resolve()
    if not input_path.is_file():
        raise click.ClickException(f"PostgreSQL dump input file does not exist: {input_path}")
    container_id = docker_mapped_postgres_container(
        options.connection.host, options.connection.port
    )
    _validate_archive(options, input_path, container_id=container_id)
    if container_id is not None:
        _restore_with_mapped_container(options, input_path, container_id)
        return input_path
    if shutil.which("pg_restore") is not None:
        _restore_with_local_client(options, input_path)
        return input_path
    image, reason = docker_postgres_image(options.client_image)
    if image is None:
        raise click.ClickException(f"pg_restore is not available. {reason}")
    _restore_with_docker(options, input_path, image)
    return input_path


def _validate_archive(
    options: PostgresRestoreOptions,
    input_path: Path,
    *,
    container_id: str | None = None,
) -> None:
    if container_id is not None:
        _validate_archive_with_mapped_container(options, input_path, container_id)
        return
    if shutil.which("pg_restore") is not None:
        result = run_command(["pg_restore", "--list", str(input_path)])
        ensure_command_succeeded(result, "pg_restore archive validation")
        return
    image, reason = docker_postgres_image(options.client_image)
    if image is None:
        raise click.ClickException(f"pg_restore is not available. {reason}")
    docker_input = PurePosixPath("/backup") / input_path.name
    command = [
        "docker",
        "run",
        "--rm",
        "--mount",
        docker_bind_mount(input_path.parent, "/backup", read_only=True),
        "--entrypoint",
        "pg_restore",
        image,
        "--list",
        str(docker_input),
    ]
    result = run_command(command)
    ensure_command_succeeded(result, "Docker pg_restore archive validation")


def _restore_with_local_client(options: PostgresRestoreOptions, input_path: Path) -> None:
    with pgpass_environment(options.connection) as environment:
        result = run_command(pg_restore_command_args(options, input_path), environment)
    ensure_command_succeeded(result, "pg_restore")


def _validate_archive_with_mapped_container(
    options: PostgresRestoreOptions, input_path: Path, container_id: str
) -> None:
    container_input = f"/tmp/dbtalk-pg-restore-{uuid.uuid4().hex}.dump"
    environment = docker_password_environment(options.connection)
    try:
        copy_command = ["docker", "cp", str(input_path), f"{container_id}:{container_input}"]
        ensure_command_succeeded(run_command(copy_command, environment), "Container archive copy")
        command = [
            "docker",
            "exec",
            "--env",
            "PGPASSWORD",
            container_id,
            "pg_restore",
            "--list",
            container_input,
        ]
        result = run_command(command, environment)
        ensure_command_succeeded(result, "Container pg_restore archive validation")
    finally:
        with contextlib.suppress(OSError):
            run_command(["docker", "exec", container_id, "rm", "-f", container_input])


def _restore_with_mapped_container(
    options: PostgresRestoreOptions, input_path: Path, container_id: str
) -> None:
    """Run pg_restore inside the mapped database container over its Unix socket."""

    container_input = f"/tmp/dbtalk-pg-restore-{uuid.uuid4().hex}.dump"
    environment = docker_password_environment(options.connection)
    try:
        copy_command = ["docker", "cp", str(input_path), f"{container_id}:{container_input}"]
        ensure_command_succeeded(run_command(copy_command, environment), "Container archive copy")
        command = [
            "docker",
            "exec",
            "--env",
            "PGPASSWORD",
            container_id,
            *pg_restore_command_args(
                options,
                PurePosixPath(container_input),
                mapped_container=True,
            ),
        ]
        result = run_command(command, environment)
        ensure_command_succeeded(result, "Container pg_restore")
    finally:
        with contextlib.suppress(OSError):
            run_command(["docker", "exec", container_id, "rm", "-f", container_input])


def _restore_with_docker(
    options: PostgresRestoreOptions,
    input_path: Path,
    image: str,
) -> None:
    docker_input = PurePosixPath("/backup") / input_path.name
    command = ["docker", "run", "--rm"]
    command.extend(docker_host_gateway_args(options.connection.host))
    command.extend(
        [
            "--env",
            "PGPASSWORD",
            "--mount",
            docker_bind_mount(input_path.parent, "/backup", read_only=True),
            "--entrypoint",
            "pg_restore",
            image,
            *pg_restore_command_args(options, docker_input, docker=True)[1:],
        ]
    )
    result = run_command(command, docker_password_environment(options.connection))
    ensure_command_succeeded(result, "Docker pg_restore")
