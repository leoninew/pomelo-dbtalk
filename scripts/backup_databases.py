#!/usr/bin/env python3
"""Sequentially dump the databases declared in backup_databases.yaml.

The YAML file contains connection metadata, database names, and the names of
environment variables holding complete DSNs. DSN values are loaded from the
process environment or from the .env file next to this script; process
environment values take precedence.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

import yaml
from dotenv import dotenv_values, load_dotenv
from sqlalchemy.engine import make_url

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "backup_databases.yaml"
Engine = Literal["mysql", "postgres"]


@dataclass(frozen=True)
class BackupTarget:
    engine: Engine
    connection: str
    database: str
    dsn_env: str
    output_label: str


@dataclass(frozen=True)
class BackupConfig:
    output_directory: Path
    targets: tuple[BackupTarget, ...]


@dataclass(frozen=True)
class BackupArtifact:
    target: BackupTarget
    destination: Path
    size_bytes: int


class BackupError(RuntimeError):
    """Raised when the backup run cannot safely continue."""


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back up databases or test configured database connections."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser(
        "backup",
        help="Dump the databases declared in a YAML configuration.",
        description="Sequentially dump the databases declared in a YAML configuration.",
    )
    backup_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Backup YAML path (default: scripts/backup_databases.yaml).",
    )
    backup_parser.add_argument(
        "--dbtalk-command",
        default="dbtalk",
        help="dbtalk executable or path (default: dbtalk).",
    )
    mode = backup_parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="List configured dumps without checking DSNs or creating files (default).",
    )
    mode.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Execute the configured dumps and write the backup manifest.",
    )
    backup_parser.set_defaults(dry_run=True)

    test_parser = subparsers.add_parser(
        "test",
        help="Test all DBTALK_* DSNs declared in scripts/.env.",
        description="Test all DBTALK_* DSNs declared in scripts/.env.",
    )
    test_parser.add_argument(
        "--dbtalk-command",
        default="dbtalk",
        help="dbtalk executable or path (default: dbtalk).",
    )
    test_parser.add_argument(
        "--timeout",
        type=positive_integer,
        default=10,
        help="Maximum query time in seconds (default: 10).",
    )
    return parser


def _mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise BackupError(f"{context} must be a YAML mapping with string keys")
    return dict(value)


def _required_string(values: Mapping[str, object], key: str, context: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BackupError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _parse_engine(values: Mapping[str, object], context: str) -> Engine:
    value = _required_string(values, "engine", context)
    if value not in {"mysql", "postgres"}:
        raise BackupError(f"{context}.engine must be mysql or postgres")
    return cast(Engine, value)


def load_backup_config(config_path: Path) -> BackupConfig:
    config_path = config_path.expanduser().resolve()
    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BackupError(f"could not read backup config: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise BackupError(f"could not parse backup config: {config_path}") from exc

    config = _mapping(raw_config, "config")
    output_value = _required_string(config, "output_directory", "config")
    output_directory = Path(output_value)
    if not output_directory.is_absolute():
        output_directory = config_path.parent / output_directory

    connections_value = config.get("connections")
    connections = _mapping(connections_value, "config.connections")
    if not connections:
        raise BackupError("config.connections must not be empty")

    targets: list[BackupTarget] = []
    for connection_name, raw_connection in connections.items():
        connection_context = f"config.connections.{connection_name}"
        connection_config = _mapping(raw_connection, connection_context)
        engine = _parse_engine(connection_config, connection_context)
        address = _required_string(connection_config, "address", connection_context)
        raw_databases = connection_config.get("databases")
        if not isinstance(raw_databases, list) or not raw_databases:
            raise BackupError(f"{connection_context}.databases must be a non-empty list")

        output_label = "-".join((engine, safe_component(connection_name), safe_component(address)))
        for index, raw_database in enumerate(raw_databases, 1):
            database_context = f"{connection_context}.databases[{index}]"
            database_config = _mapping(raw_database, database_context)
            targets.append(
                BackupTarget(
                    engine=engine,
                    connection=address,
                    database=_required_string(database_config, "name", database_context),
                    dsn_env=_required_string(database_config, "dsn_env", database_context),
                    output_label=output_label,
                )
            )

    if not targets:
        raise BackupError("backup config contains no databases")
    return BackupConfig(output_directory=output_directory.resolve(), targets=tuple(targets))


def load_connection_environment() -> None:
    """Load only the .env file located next to this script."""

    load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=False)


def load_dsn_environment_names() -> tuple[str, ...]:
    """Return DBTALK_* names declared in the .env file next to this script."""

    dotenv_path = SCRIPT_DIR / ".env"
    try:
        values = dotenv_values(dotenv_path=dotenv_path)
    except OSError as exc:
        raise BackupError(f"could not read environment file: {dotenv_path}") from exc

    names = sorted(name for name in values if name.startswith("DBTALK_"))
    if not names:
        raise BackupError(f"no DBTALK_* variables found in environment file: {dotenv_path}")
    return tuple(names)


def require_dsn_envs(targets: Sequence[BackupTarget]) -> None:
    missing = sorted({target.dsn_env for target in targets if not os.environ.get(target.dsn_env)})
    if missing:
        raise BackupError("missing DSN environment variables: " + ", ".join(missing))

    for target in targets:
        dsn = os.environ[target.dsn_env]
        try:
            dsn_database = make_url(dsn).database
        except Exception as exc:
            raise BackupError(f"invalid DSN in environment variable {target.dsn_env}") from exc
        if dsn_database != target.database:
            raise BackupError(
                f"DSN environment variable {target.dsn_env} targets database "
                f"{dsn_database or '<none>'}, expected {target.database}"
            )


def resolve_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved:
        return resolved

    command_path = Path(command)
    if command_path.is_file():
        return str(command_path.resolve())
    raise BackupError(f"dbtalk executable was not found: {command}")


def safe_component(value: str) -> str:
    component = "".join(
        character if character.isalnum() or character in "-_." else "-" for character in value
    )
    return component.strip("-") or "unknown"


def display_path(path: Path) -> str:
    """Render a path relative to the repository for concise logs and manifests."""

    relative = os.path.relpath(path.resolve(), REPOSITORY_ROOT)
    return Path(relative).as_posix()


def batch_directory(output_directory: Path, batch_timestamp: str) -> Path:
    candidate = output_directory / batch_timestamp
    sequence = 1
    while candidate.exists():
        candidate = output_directory / f"{batch_timestamp}-{sequence:02d}"
        sequence += 1
    return candidate


def output_path(target: BackupTarget, output_directory: Path) -> Path:
    extension = ".dump" if target.engine == "postgres" else ".sql.gz"
    stem = "-".join((target.output_label, safe_component(target.database)))
    candidate = output_directory / f"{stem}{extension}"
    sequence = 1
    while candidate.exists():
        candidate = output_directory / f"{stem}-{sequence:02d}{extension}"
        sequence += 1
    return candidate


def manifest_path(output_directory: Path) -> Path:
    candidate = output_directory / "backup-manifest.md"
    sequence = 1
    while candidate.exists():
        candidate = output_directory / f"backup-manifest-{sequence:02d}.md"
        sequence += 1
    return candidate


def markdown_value(value: str) -> str:
    escaped = value.replace("`", "'")
    return f"`{escaped}`"


def write_manifest(
    config_path: Path,
    artifacts: Sequence[BackupArtifact],
    batch_directory: Path,
    batch_timestamp: str,
) -> Path:
    destination = manifest_path(batch_directory)
    lines = [
        "# Database Backup Manifest",
        "",
        f"- Generated at (local): `{batch_timestamp}`",
        f"- Configuration: `{display_path(config_path)}`",
        f"- Output directory: `{display_path(batch_directory)}`",
        f"- Backups: `{len(artifacts)}`",
        "",
        "DSN values are intentionally omitted. Each backup used the DSN from "
        "the environment variable shown below.",
        "",
    ]
    for index, artifact in enumerate(artifacts, 1):
        target = artifact.target
        format_name = (
            "PostgreSQL custom archive" if target.engine == "postgres" else "MySQL SQL dump (gzip)"
        )
        relative_output = artifact.destination.relative_to(batch_directory).as_posix()
        lines.extend(
            [
                f"## {index}. {markdown_value(target.database)}",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| Engine | {markdown_value(target.engine)} |",
                f"| Source connection | {markdown_value(target.connection)} |",
                f"| Database | {markdown_value(target.database)} |",
                f"| DSN environment variable | {markdown_value(target.dsn_env)} |",
                f"| Backup file | {markdown_value(relative_output)} |",
                f"| Format | {format_name} |",
                f"| Size (bytes) | `{artifact.size_bytes}` |",
                "",
            ]
        )

    try:
        destination.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"could not write backup manifest: {destination}") from exc
    return destination


def run_dump(dbtalk: str, target: BackupTarget, destination: Path) -> None:
    command = [
        dbtalk,
        target.engine,
        "dump",
        "--dsn-env",
        target.dsn_env,
        "--output",
        str(destination),
    ]
    if target.engine == "mysql":
        command.append("--archive")

    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError(
            "dbtalk dump failed "
            f"engine={target.engine} connection={target.connection} "
            f"database={target.database} exit_code={result.returncode}"
        )
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise BackupError(f"dbtalk dump produced no usable file: {destination}")


def run_dsn_test(dbtalk: str, dsn_env: str, timeout_seconds: int) -> bool:
    command = [
        dbtalk,
        "database",
        "query",
        "--dsn-env",
        dsn_env,
        "--sql",
        "SELECT 1",
        "--timeout",
        str(timeout_seconds),
        "--format",
        "json",
    ]
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def run_backups(args: argparse.Namespace) -> int:
    backup_config = load_backup_config(args.config)
    batch_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_output_directory = batch_directory(backup_config.output_directory, batch_timestamp)
    total = len(backup_config.targets)

    logging.info(
        "backup run started targets=%d config=%s output_dir=%s batch_dir=%s timestamp=%s",
        total,
        args.config.expanduser().resolve(),
        backup_config.output_directory,
        batch_output_directory,
        batch_timestamp,
    )

    dbtalk = None
    if not args.dry_run:
        load_connection_environment()
        require_dsn_envs(backup_config.targets)
        dbtalk = resolve_command(args.dbtalk_command)
        batch_output_directory.mkdir(parents=True, exist_ok=True)

    artifacts: list[BackupArtifact] = []
    for index, target in enumerate(backup_config.targets, 1):
        destination = output_path(target, batch_output_directory)
        logging.info(
            "backup planned index=%d/%d engine=%s connection=%s database=%s output=%s",
            index,
            total,
            target.engine,
            target.connection,
            target.database,
            display_path(destination),
        )
        if args.dry_run:
            continue

        logging.info(
            "backup started index=%d/%d engine=%s database=%s",
            index,
            total,
            target.engine,
            target.database,
        )
        assert dbtalk is not None
        started_at = time.perf_counter()
        run_dump(dbtalk, target, destination)
        duration_seconds = time.perf_counter() - started_at
        artifact = BackupArtifact(
            target=target,
            destination=destination,
            size_bytes=destination.stat().st_size,
        )
        artifacts.append(artifact)
        logging.info(
            "backup completed index=%d/%d engine=%s database=%s bytes=%d duration_seconds=%.3f",
            index,
            total,
            target.engine,
            target.database,
            artifact.size_bytes,
            duration_seconds,
        )

    if args.dry_run:
        logging.info("dry run completed targets=%d", total)
    else:
        manifest = write_manifest(
            args.config.expanduser().resolve(),
            artifacts,
            batch_output_directory,
            batch_timestamp,
        )
        logging.info("backup manifest written path=%s", manifest)
        logging.info("backup run completed targets=%d", total)
    return 0


def run_tests(args: argparse.Namespace) -> int:
    dsn_envs = load_dsn_environment_names()
    load_connection_environment()
    dbtalk = resolve_command(args.dbtalk_command)

    total = len(dsn_envs)
    passed = 0
    logging.info("dsn test run started variables=%d timeout_seconds=%d", total, args.timeout)
    for index, dsn_env in enumerate(dsn_envs, 1):
        logging.info("dsn test started index=%d/%d variable=%s", index, total, dsn_env)
        started_at = time.perf_counter()
        succeeded = run_dsn_test(dbtalk, dsn_env, args.timeout)
        duration_seconds = time.perf_counter() - started_at
        if succeeded:
            passed += 1
            logging.info(
                "dsn test passed index=%d/%d variable=%s duration_seconds=%.3f",
                index,
                total,
                dsn_env,
                duration_seconds,
            )
        else:
            logging.error(
                "dsn test failed index=%d/%d variable=%s duration_seconds=%.3f",
                index,
                total,
                dsn_env,
                duration_seconds,
            )

    failed = total - passed
    logging.info("dsn test run completed variables=%d passed=%d failed=%d", total, passed, failed)
    return 0 if failed == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    args = build_parser().parse_args(argv)
    try:
        if args.command == "backup":
            return run_backups(args)
        if args.command == "test":
            return run_tests(args)
        raise BackupError(f"unsupported command: {args.command}")
    except BackupError:
        logging.exception("%s run failed", args.command)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
