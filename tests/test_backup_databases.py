from __future__ import annotations

import importlib.util
import logging
import shlex
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "backup_databases.py"
SPEC = importlib.util.spec_from_file_location("backup_databases_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
backup_databases = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup_databases
SPEC.loader.exec_module(backup_databases)


def test_parser_places_existing_options_under_backup() -> None:
    backup_args = backup_databases.build_parser().parse_args(["backup"])
    assert backup_args.command == "backup"
    assert backup_args.dry_run is True
    assert backup_args.config == backup_databases.DEFAULT_CONFIG_PATH

    test_args = backup_databases.build_parser().parse_args(["test", "--timeout", "7"])
    assert test_args.command == "test"
    assert test_args.timeout == 7


def test_resolve_command_preserves_path_command_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup_databases.shutil, "which", lambda command: "/bin/dbtalk")

    assert backup_databases.resolve_command("dbtalk") == "dbtalk"


def test_load_backup_config_reads_inline_dsn_from_dynaconf_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "backup_databases.yaml"
    config_path.write_text(
        "output_directory: ../data\n"
        "connections:\n"
        "  local:\n"
        "    engine: mysql\n"
        "    address: localhost:3306\n"
        "    databases:\n"
        "      - name: app\n"
        "        dsn: 'sqlite:///app'\n",
        encoding="utf-8",
    )

    config = backup_databases.load_backup_config(config_path)

    assert config.targets[0].dsn == "sqlite:///app"
    assert config.targets[0].database == "app"


def test_load_backup_config_uses_process_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "backup_databases.yaml"
    config_path.write_text(
        "output_directory: ../data\n"
        "connections:\n"
        "  local:\n"
        "    engine: mysql\n"
        "    address: localhost:3306\n"
        "    databases:\n"
        "      - name: app\n"
        "        dsn: 'sqlite:///yaml'\n"
        "        enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBTALK_OUTPUT_DIRECTORY", "../overridden-data")

    config = backup_databases.load_backup_config(config_path)

    assert config.targets[0].dsn == "sqlite:///yaml"
    assert config.output_directory == (tmp_path / "../overridden-data").resolve()


def test_disabled_targets_are_skipped_by_connection_tests(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_path = tmp_path / "backup_databases.yaml"
    config_path.write_text(
        "output_directory: ../data\n"
        "connections:\n"
        "  local:\n"
        "    engine: mysql\n"
        "    address: localhost:3306\n"
        "    databases:\n"
        "      - name: enabled\n"
        "        dsn: 'sqlite:///enabled'\n"
        "        enabled: true\n"
        "      - name: disabled\n"
        "        dsn: 'not-a-dsn'\n"
        "        enabled: false\n",
        encoding="utf-8",
    )
    args = Namespace(config=config_path, dbtalk_command="dbtalk", timeout=3)
    with (
        patch.object(backup_databases, "resolve_command", return_value="dbtalk"),
        patch.object(backup_databases, "run_dsn_test", return_value=True) as run_test,
        caplog.at_level(logging.INFO),
    ):
        assert backup_databases.run_tests(args) == 0

    assert run_test.call_args.args[:3] == ("dbtalk", "sqlite:///enabled", 3)
    assert "dsn test skipped connection=local database=disabled enabled=False" in caplog.text


def test_batch_directory_uses_timestamp_and_avoids_existing_directory(tmp_path: Path) -> None:
    timestamp = "20260831-120000"
    expected = tmp_path / timestamp

    assert backup_databases.batch_directory(tmp_path, timestamp) == expected

    expected.mkdir()
    assert backup_databases.batch_directory(tmp_path, timestamp) == tmp_path / f"{timestamp}-01"


def test_display_path_is_repository_relative_and_posix() -> None:
    path = backup_databases.REPOSITORY_ROOT / "data" / "20260831-120000" / "backup.dump"

    assert backup_databases.display_path(path) == "data/20260831-120000/backup.dump"


def test_output_path_does_not_include_batch_timestamp(tmp_path: Path) -> None:
    target = backup_databases.BackupTarget(
        engine="postgres",
        connection="10.0.0.1:5432",
        connection_name="remote",
        database="app",
        dsn="postgresql+psycopg://user:password@host:5432/app",
        enabled=True,
        output_label="postgres-remote-10.0.0.1-5432",
    )

    output = backup_databases.output_path(target, tmp_path / "20260831-120000")

    assert output.name == "postgres-remote-10.0.0.1-5432-app.dump"


def test_manifest_is_written_inside_batch_directory_with_relative_output(tmp_path: Path) -> None:
    batch_directory = tmp_path / "batch"
    target = backup_databases.BackupTarget(
        engine="mysql",
        connection="10.0.0.1:3306",
        connection_name="think_mysql",
        database="app",
        dsn="mysql+pymysql://user:password@host:3306/app",
        enabled=True,
        output_label="mysql-remote-10.0.0.1-3306",
    )
    second_target = backup_databases.BackupTarget(
        engine="mysql",
        connection="10.0.0.1:3306",
        connection_name="think_mysql",
        database="audit",
        dsn="mysql+pymysql://user:password@host:3306/audit",
        enabled=True,
        output_label="mysql-remote-10.0.0.1-3306",
    )
    artifact = backup_databases.BackupArtifact(
        target=target,
        destination=batch_directory / "mysql-remote-10.0.0.1-3306-app.sql.gz",
        size_bytes=12,
    )
    second_artifact = backup_databases.BackupArtifact(
        target=second_target,
        destination=batch_directory / "mysql-remote-10.0.0.1-3306-audit.sql.gz",
        size_bytes=14,
    )

    manifest_path = tmp_path / "manifest.md"
    with patch.object(backup_databases, "manifest_path", return_value=manifest_path):
        manifest = backup_databases.write_manifest(
            tmp_path / "backup_databases.yaml",
            [artifact, second_artifact],
            batch_directory,
            "20260831-120000",
        )

    assert manifest == manifest_path
    content = manifest.read_text(encoding="utf-8")
    assert "## 1. `think_mysql`" in content
    assert "`mysql` at `10.0.0.1:3306`" in content
    assert "| Database | Backup file | Format | Size |" in content
    assert "| `app` | `mysql-remote-10.0.0.1-3306-app.sql.gz` |" in content
    assert "| `audit` | `mysql-remote-10.0.0.1-3306-audit.sql.gz` |" in content
    assert content.count("## 1. `think_mysql`") == 1


def test_run_dsn_test_uses_read_only_database_query(caplog: pytest.LogCaptureFixture) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    with (
        patch.object(backup_databases.subprocess, "run", return_value=completed) as run,
        caplog.at_level(logging.INFO),
    ):
        assert backup_databases.run_dsn_test(
            "dbtalk", "sqlite:///app", 7
        ) is True

    command = run.call_args.args[0]
    assert command == [
        "dbtalk",
        "database",
        "query",
        "--dsn-env",
        "DBTALK_BACKUP_DSN",
        "--sql",
        "SELECT 1",
        "--timeout",
        "7",
        "--format",
        "json",
    ]
    assert run.call_args.kwargs["cwd"] == backup_databases.REPOSITORY_ROOT
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["check"] is False
    assert "dbtalk command=dbtalk database query --dsn-env DBTALK_BACKUP_DSN" in caplog.text


def test_run_dump_logs_the_dbtalk_command(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    destination = tmp_path / "backup.sql.gz"
    target = backup_databases.BackupTarget(
        engine="mysql",
        connection="127.0.0.1:3306",
        connection_name="local",
        database="app",
        dsn="mysql+pymysql://user:password@host:3306/app",
        enabled=True,
        output_label="mysql-local-127.0.0.1-3306",
    )
    completed = subprocess.CompletedProcess([], 0, "", "")

    def create_output(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        destination.write_bytes(b"backup")
        return completed

    with (
        patch.object(backup_databases.subprocess, "run", side_effect=create_output) as run,
        caplog.at_level(logging.INFO),
    ):
        backup_databases.run_dump("dbtalk", target, destination)

    assert run.call_args.args[0] == [
        "dbtalk",
        "mysql",
        "dump",
        "--dsn-env",
        "DBTALK_BACKUP_DSN",
        "--output",
        str(destination),
        "--archive",
    ]
    assert f"dbtalk command={shlex.join(run.call_args.args[0])}" in caplog.text


def test_run_tests_reports_each_result_and_returns_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "backup_databases.yaml"
    config_path.write_text(
        "output_directory: ../data\n"
        "connections:\n"
        "  local:\n"
        "    engine: mysql\n"
        "    address: localhost:3306\n"
        "    databases:\n"
        "      - name: a\n"
        "        dsn: 'sqlite:///a'\n"
        "        enabled: true\n"
        "      - name: b\n"
        "        dsn: 'sqlite:///b'\n"
        "        enabled: true\n",
        encoding="utf-8",
    )
    args = Namespace(config=config_path, dbtalk_command="dbtalk", timeout=3)
    with (
        patch.object(backup_databases, "resolve_command", return_value="dbtalk"),
        patch.object(backup_databases, "run_dsn_test", side_effect=[True, False]) as run_test,
        caplog.at_level(logging.INFO),
    ):
        result = backup_databases.run_tests(args)

    assert result == 1
    assert run_test.call_args_list[0].args[:3] == ("dbtalk", "sqlite:///a", 3)
    assert run_test.call_args_list[1].args[:3] == ("dbtalk", "sqlite:///b", 3)
    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("dsn test passed ") for message in messages)
    assert any(message.startswith("dsn test failed ") for message in messages)
    assert "dsn test run completed variables=2 passed=1 failed=1" in messages
