#!/usr/bin/env python3
"""Sequentially dump databases declared in a Dynaconf YAML configuration."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from dynaconf import Dynaconf
from sqlalchemy.engine import make_url

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "backup_databases.yaml"
ENV_PREFIX = "DBTALK"
Engine = Literal["mysql", "postgres"]


@dataclass(frozen=True)
class BackupTarget:
    engine: Engine
    connection: str
    connection_name: str
    database: str
    dsn: str
    enabled: bool
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
        help="Test all DSNs declared in the selected backup configuration.",
        description="Test all DSNs declared in the selected backup configuration.",
    )
    test_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Backup YAML path (default: scripts/backup_databases.yaml).",
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


def _parse_enabled(values: Mapping[str, object], context: str) -> bool:
    value = values.get("enabled", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise BackupError(f"{context}.enabled must be a boolean")


def load_backup_config(config_path: Path) -> BackupConfig:
    config_path = config_path.expanduser().resolve()
    if not config_path.is_file():
        raise BackupError(f"could not read backup config: {config_path}")

    try:
        dynaconf = Dynaconf(
            settings_files=[str(config_path)],
            envvar_prefix=ENV_PREFIX,
            environments=False,
        )
        config = {
            str(key).lower(): value for key, value in _mapping(dynaconf.to_dict(), "config").items()
        }
    except (OSError, ValueError, TypeError) as exc:
        raise BackupError(f"could not load backup config: {config_path}") from exc

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
                    connection_name=connection_name,
                    database=_required_string(database_config, "name", database_context),
                    dsn=_required_string(database_config, "dsn", database_context),
                    enabled=_parse_enabled(database_config, database_context),
                    output_label=output_label,
                )
            )

    if not targets:
        raise BackupError("backup config contains no databases")

    return BackupConfig(
        output_directory=output_directory.resolve(),
        targets=tuple(targets),
    )


def require_dsns(targets: Sequence[BackupTarget]) -> None:
    for target in targets:
        try:
            dsn_database = make_url(target.dsn).database
        except Exception as exc:
            raise BackupError(
                f"invalid DSN for {target.connection_name}.{target.database}"
            ) from exc
        if dsn_database != target.database:
            raise BackupError(
                f"DSN for {target.connection_name}.{target.database} targets database "
                f"{dsn_database or '<none>'}, expected {target.database}"
            )


def resolve_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved:
        # Let subprocess resolve PATH commands so logs retain the configured name.
        return command

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
        "DSN values are intentionally omitted from this manifest.",
        "",
    ]
    grouped_artifacts: dict[str, list[BackupArtifact]] = {}
    for artifact in artifacts:
        grouped_artifacts.setdefault(artifact.target.connection_name, []).append(artifact)

    for connection_index, (connection_name, connection_artifacts) in enumerate(
        grouped_artifacts.items(), 1
    ):
        connection_target = connection_artifacts[0].target
        lines.extend(
            [
                f"## {connection_index}. {markdown_value(connection_name)}",
                "",
                f"{markdown_value(connection_target.engine)} at "
                f"{markdown_value(connection_target.connection)}",
                "",
                "| Database | Backup file | Format | Size |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for artifact in connection_artifacts:
            target = artifact.target
            format_name = (
                "PostgreSQL custom archive"
                if target.engine == "postgres"
                else "MySQL SQL dump (gzip)"
            )
            relative_output = artifact.destination.relative_to(batch_directory).as_posix()
            lines.extend(
                [
                    f"| {markdown_value(target.database)} | "
                    f"{markdown_value(relative_output)} | {format_name} | "
                    f"{artifact.size_bytes:,} bytes |",
                ]
            )
        lines.append("")

    try:
        destination.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"could not write backup manifest: {destination}") from exc
    return destination


def run_dump(
    dbtalk: str,
    target: BackupTarget,
    destination: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    dsn_env = "DBTALK_BACKUP_DSN"
    command = [
        dbtalk,
        target.engine,
        "dump",
        "--dsn-env",
        dsn_env,
        "--output",
        str(destination),
    ]
    if target.engine == "mysql":
        command.append("--archive")

    logging.info("dbtalk command=%s", shlex.join(command))
    child_environment = dict(environment) if environment is not None else os.environ.copy()
    child_environment[dsn_env] = target.dsn
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=child_environment,
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


def run_dsn_test(
    dbtalk: str,
    dsn: str,
    timeout_seconds: int,
    environment: Mapping[str, str] | None = None,
) -> bool:
    dsn_env = "DBTALK_BACKUP_DSN"
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
    logging.info("dbtalk command=%s", shlex.join(command))
    child_environment = dict(environment) if environment is not None else os.environ.copy()
    child_environment[dsn_env] = dsn
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=child_environment,
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
    enabled_targets = tuple(target for target in backup_config.targets if target.enabled)
    if not args.dry_run:
        require_dsns(enabled_targets)
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
        if not target.enabled:
            logging.info(
                "backup skipped index=%d/%d connection=%s database=%s enabled=%s",
                index,
                total,
                target.connection_name,
                target.database,
                target.enabled,
            )
            continue
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
    backup_config = load_backup_config(args.config)
    enabled_targets = tuple(target for target in backup_config.targets if target.enabled)
    require_dsns(enabled_targets)
    dbtalk = resolve_command(args.dbtalk_command)

    total = len(enabled_targets)
    passed = 0
    logging.info("dsn test run started variables=%d timeout_seconds=%d", total, args.timeout)
    for target in backup_config.targets:
        if not target.enabled:
            logging.info(
                "dsn test skipped connection=%s database=%s enabled=%s",
                target.connection_name,
                target.database,
                target.enabled,
            )
    for index, target in enumerate(enabled_targets, 1):
        logging.info(
            "dsn test started index=%d/%d connection=%s database=%s",
            index,
            total,
            target.connection_name,
            target.database,
        )
        started_at = time.perf_counter()
        succeeded = run_dsn_test(dbtalk, target.dsn, args.timeout)
        duration_seconds = time.perf_counter() - started_at
        if succeeded:
            passed += 1
            logging.info(
                "dsn test passed index=%d/%d connection=%s database=%s duration_seconds=%.3f",
                index,
                total,
                target.connection_name,
                target.database,
                duration_seconds,
            )
        else:
            logging.error(
                "dsn test failed index=%d/%d connection=%s database=%s duration_seconds=%.3f",
                index,
                total,
                target.connection_name,
                target.database,
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
