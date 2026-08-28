from __future__ import annotations

import logging
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from dbtalk.cli import cli as main_command
from dbtalk.mysql.dump import MysqlDumpOptions, dump_database, dump_with_mapped_container
from dbtalk.mysql.restore import MysqlRestoreOptions, restore_database


def test_dump_lifecycle_logs_include_operation_and_final_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    output = tmp_path / "backup.sql"
    options = MysqlDumpOptions(
        host="localhost",
        port=3306,
        user="backup",
        password="secret",
        database="logs",
        output=output,
    )

    def write_dump(
        command: list[str], environment: dict[str, str], **_: object
    ) -> CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"USE `logs`;\n")
        return CompletedProcess(command, 0, "", "")

    with (
        patch("dbtalk.mysql.dump.docker_mapped_mysql_container", return_value=None),
        patch("dbtalk.mysql.dump.shutil.which", return_value="mysqldump"),
        patch("dbtalk.mysql.dump.run_command", side_effect=write_dump),
        caplog.at_level(logging.INFO, logger="dbtalk"),
    ):
        result = dump_database(options)

    messages = [record.getMessage() for record in caplog.records]
    lifecycle = [message for message in messages if message.startswith("mysql dump ")]
    assert result == output.resolve()
    assert any(message.startswith("mysql dump started ") for message in lifecycle)
    assert any(message.startswith("mysql dump progress ") for message in lifecycle)
    completed = next(
        message for message in lifecycle if message.startswith("mysql dump completed ")
    )
    assert "elapsed_ms=" in completed
    assert "bytes=12" in completed
    assert "output=" in completed


def test_restore_lifecycle_logs_are_sanitized_and_preflighted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    input_path = tmp_path / "backup.sql"
    input_path.write_text("SELECT 1;\n", encoding="utf-8")
    options = MysqlRestoreOptions(
        host="db.example.test",
        port=3307,
        user="restore",
        password="secret",
        input=input_path,
        database="logs",
    )
    failure = CompletedProcess(
        [],
        1,
        "",
        "Access denied password=secret mysql+pymysql://restore:secret@db.example.test/logs",
    )

    with (
        patch("dbtalk.mysql.restore.shutil.which", return_value="mysql"),
        patch("dbtalk.mysql.restore.run_command", return_value=failure),
        caplog.at_level(logging.INFO, logger="dbtalk"),
    ):
        try:
            restore_database(options)
        except click.ClickException as error:
            assert "secret" not in str(error)
        else:
            raise AssertionError("restore should fail during target preflight")

    messages = [record.getMessage() for record in caplog.records]
    lifecycle = [message for message in messages if message.startswith("mysql restore ")]
    assert any(message.startswith("mysql restore started ") for message in lifecycle)
    failed = next(message for message in lifecycle if message.startswith("mysql restore failed "))
    assert "elapsed_ms=" in failed
    assert "stage=preflight" in failed
    assert "secret" not in failed
    assert "<redacted>" in failed


def test_dump_logs_prepare_failures(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    options = MysqlDumpOptions(
        host="localhost",
        port=3306,
        user="backup",
        password="secret",
        database="logs",
        output=tmp_path / "backup.sql",
    )

    with (
        patch(
            "dbtalk.mysql.dump.temporary_path",
            side_effect=click.ClickException("temporary directory is not writable"),
        ),
        caplog.at_level(logging.INFO, logger="dbtalk"),
        pytest.raises(click.ClickException, match="not writable"),
    ):
        dump_database(options)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("mysql dump started ") for message in messages)
    assert any(
        "mysql dump failed " in message and "stage=prepare" in message for message in messages
    )


def test_mapped_dump_reports_unmeasurable_container_progress(tmp_path: Path) -> None:
    output = tmp_path / "backup.sql"
    options = MysqlDumpOptions(
        host="localhost",
        port=3306,
        user="backup",
        password="secret",
        database="logs",
        output=output,
    )
    progress: list[int] = []

    def run_docker(
        command: list[str], environment: dict[str, str] | None = None, **_: object
    ) -> CompletedProcess[str]:
        if command[1] == "cp":
            output.write_text("SELECT 1;\n", encoding="utf-8")
        return CompletedProcess(command, 0, "", "")

    with patch("dbtalk.mysql.dump.run_command", side_effect=run_docker):
        dump_with_mapped_container(
            options,
            output,
            "mysql-server",
            progress_callback=progress.append,
        )

    assert progress[0] == -1
    assert progress[-1] == output.stat().st_size


def test_mysql_help_exposes_only_the_new_dump_restore_contract() -> None:
    runner = CliRunner()

    dump_help = runner.invoke(main_command, ["mysql", "dump", "--help"])
    restore_help = runner.invoke(main_command, ["mysql", "restore", "--help"])

    assert dump_help.exit_code == 0, dump_help.output
    assert "--skip-definer" in dump_help.output
    assert "--create-database" not in dump_help.output
    assert "--drop-database" not in dump_help.output
    assert restore_help.exit_code == 0, restore_help.output
    assert "--database TARGET" in restore_help.output
    assert "--input FILE" in restore_help.output
