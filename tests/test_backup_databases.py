from __future__ import annotations

import importlib.util
import logging
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


def test_load_dsn_environment_names_reads_only_db_talk_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "DBTALK_Z_DSN=mysql+pymysql://user:password@host/z\n"
        "APP_DSN=sqlite:///:memory:\n"
        "DBTALK_A_DSN=postgresql+psycopg://user:password@host/a\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(backup_databases, "SCRIPT_DIR", tmp_path)

    assert backup_databases.load_dsn_environment_names() == (
        "DBTALK_A_DSN",
        "DBTALK_Z_DSN",
    )


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
        database="app",
        dsn_env="DBTALK_APP_DSN",
        output_label="postgres-remote-10.0.0.1-5432",
    )

    output = backup_databases.output_path(target, tmp_path / "20260831-120000")

    assert output.name == "postgres-remote-10.0.0.1-5432-app.dump"


def test_manifest_is_written_inside_batch_directory_with_relative_output(tmp_path: Path) -> None:
    batch_directory = tmp_path / "batch"
    target = backup_databases.BackupTarget(
        engine="mysql",
        connection="10.0.0.1:3306",
        database="app",
        dsn_env="DBTALK_APP_DSN",
        output_label="mysql-remote-10.0.0.1-3306",
    )
    artifact = backup_databases.BackupArtifact(
        target=target,
        destination=batch_directory / "mysql-remote-10.0.0.1-3306-app.sql.gz",
        size_bytes=12,
    )

    manifest_path = tmp_path / "manifest.md"
    with patch.object(backup_databases, "manifest_path", return_value=manifest_path):
        manifest = backup_databases.write_manifest(
            tmp_path / "backup_databases.yaml",
            [artifact],
            batch_directory,
            "20260831-120000",
        )

    assert manifest == manifest_path
    assert "| Backup file | `mysql-remote-10.0.0.1-3306-app.sql.gz` |" in manifest.read_text(
        encoding="utf-8"
    )


def test_run_dsn_test_uses_read_only_database_query() -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    with patch.object(backup_databases.subprocess, "run", return_value=completed) as run:
        assert backup_databases.run_dsn_test("dbtalk", "DBTALK_APP_DSN", 7) is True

    command = run.call_args.args[0]
    assert command == [
        "dbtalk",
        "database",
        "query",
        "--dsn-env",
        "DBTALK_APP_DSN",
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


def test_run_tests_reports_each_result_and_returns_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    args = Namespace(dbtalk_command="dbtalk", timeout=3)
    with (
        patch.object(
            backup_databases,
            "load_dsn_environment_names",
            return_value=("DBTALK_A_DSN", "DBTALK_B_DSN"),
        ),
        patch.object(backup_databases, "load_connection_environment"),
        patch.object(backup_databases, "resolve_command", return_value="dbtalk"),
        patch.object(backup_databases, "run_dsn_test", side_effect=[True, False]) as run_test,
        caplog.at_level(logging.INFO),
    ):
        result = backup_databases.run_tests(args)

    assert result == 1
    assert run_test.call_args_list[0].args == ("dbtalk", "DBTALK_A_DSN", 3)
    assert run_test.call_args_list[1].args == ("dbtalk", "DBTALK_B_DSN", 3)
    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("dsn test passed ") for message in messages)
    assert any(message.startswith("dsn test failed ") for message in messages)
    assert "dsn test run completed variables=2 passed=1 failed=1" in messages
