from __future__ import annotations

import contextlib
import gzip
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import click

from db_talk.settings import DEFAULT_MYSQL_PORT

LOCAL_MYSQL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def gzip_output_path(output: Path) -> Path:
    """Return the gzip path associated with a requested archive output."""
    if output.name.lower().endswith(".gz"):
        return output
    return output.with_name(f"{output.name}.gz")


def write_gzip(source: Path, output: Path) -> None:
    """Write a source file as gzip without exposing it at the final path early."""
    if not source.is_file():
        raise click.ClickException(f"gzip source file does not exist: {source}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="dbtalk-gzip-", suffix=".gz", dir=output.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with source.open("rb") as input_stream, gzip.open(temporary_path, "wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
        temporary_path.replace(output)
    except OSError as error:
        raise click.ClickException(f"could not write gzip backup: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            temporary_path.unlink()


@contextlib.contextmanager
def unpack_gzip_input(input_path: Path, required_suffix: str) -> Iterator[Path]:
    """Yield an uncompressed temporary input for a gzip path or the original path."""
    if not input_path.name.lower().endswith(".gz"):
        yield input_path
        return
    logical_name = input_path.name[: -len(".gz")]
    if not logical_name.lower().endswith(required_suffix):
        raise click.ClickException(f"gzip backup must contain a {required_suffix} file")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix="dbtalk-gzip-input-", suffix=required_suffix
    )
    temporary_path = Path(temporary_name)
    try:
        with (
            os.fdopen(descriptor, "wb") as output_stream,
            gzip.open(input_path, "rb") as input_stream,
        ):
            shutil.copyfileobj(input_stream, output_stream)
        yield temporary_path
    except (EOFError, OSError) as error:
        raise click.ClickException(f"could not read gzip backup: {error}") from error
    finally:
        with contextlib.suppress(OSError):
            temporary_path.unlink()


def mysql_client_args(executable: str, host: str, port: int, user: str, password: str) -> list[str]:
    """Build common MySQL client arguments without executing them."""
    return [
        "env",
        f"MYSQL_PWD={password}",
        executable,
        *mysql_connection_args(host, port, user),
    ]


def mysql_connection_args(host: str, port: int, user: str) -> list[str]:
    """Build connection arguments shared by MySQL client executables."""
    args: list[str] = []
    if not is_local_mysql_host(host):
        args.extend(["-h", host])
    if port != DEFAULT_MYSQL_PORT:
        args.extend(["-P", str(port)])
    args.extend(["-u", user])
    return args


def is_local_mysql_host(host: str) -> bool:
    return host.lower() in LOCAL_MYSQL_HOSTS


def docker_mysql_image() -> tuple[str | None, str]:
    """Return an available local MySQL image, preferring the latest tag."""
    if shutil.which("docker") is None:
        return None, "Docker is not installed or is not on PATH."

    try:
        result = subprocess.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", "mysql"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, "Docker could not be started."

    if result.returncode != 0:
        return (
            None,
            "Docker cannot inspect local images; check that its daemon is running.",
        )

    images = [
        image
        for line in result.stdout.splitlines()
        if (image := line.strip()).startswith("mysql:") and image != "mysql:<none>"
    ]
    if "mysql:latest" in images:
        return "mysql:latest", ""
    if images:
        return images[0], ""
    return None, "No local MySQL Docker image is available."


def docker_database_host(host: str) -> str:
    if is_local_mysql_host(host):
        return "host.docker.internal"
    return host


def docker_host_gateway_args(host: str) -> list[str]:
    if is_local_mysql_host(host) and platform.system() != "Windows":
        return ["--add-host", "host.docker.internal:host-gateway"]
    return []


def mysql_password_environment(password: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = password
    return environment


def run_command(
    command: list[str],
    environment: dict[str, str] | None = None,
    *,
    input_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        if input_path is None:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
        with input_path.open("rb") as input_stream:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                stdin=input_stream,
                env=environment,
            )
    except OSError as error:
        raise click.ClickException(f"Could not run {command[0]}: {error}") from error


def ensure_command_succeeded(result: subprocess.CompletedProcess[str], command_name: str) -> None:
    if result.returncode == 0:
        return

    detail = result.stderr.strip() or result.stdout.strip()
    if detail:
        raise click.ClickException(f"{command_name} failed: {detail}")
    raise click.ClickException(f"{command_name} failed with exit code {result.returncode}.")


def remove_temporary_container(container_name: str, environment: dict[str, str]) -> None:
    with contextlib.suppress(OSError):
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
