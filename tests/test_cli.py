"""CLI behavior tests that do not require external services."""

import click
import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from dbtalk import cli as cli_module
from dbtalk.cli import cli, main
from dbtalk.context import dbtalk_context


def test_help_lists_database_command_groups() -> None:
    result = CliRunner().invoke(cli, ["--help"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "mysql" in result.output
    assert "postgres" in result.output
    assert "database" in result.output


def test_version_is_available_without_configuration() -> None:
    result = CliRunner().invoke(cli, ["--version"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "dbtalk, version 0.1.0" in result.output


def test_root_command_displays_help() -> None:
    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert "Usage: cli" in result.output


def test_database_command_group_help_is_available() -> None:
    runner = CliRunner()
    mysql_result = runner.invoke(cli, ["mysql", "--help"])
    postgres_result = runner.invoke(cli, ["postgres", "--help"])
    database_result = runner.invoke(cli, ["database", "--help"])

    assert mysql_result.exit_code == 0, mysql_result.output
    assert "dump" in mysql_result.output
    assert "restore" in mysql_result.output
    assert postgres_result.exit_code == 0, postgres_result.output
    assert "dump" in postgres_result.output
    assert "restore" in postgres_result.output
    assert database_result.exit_code == 0, database_result.output
    assert "export" in database_result.output
    assert "import" in database_result.output


def test_context_requires_root_initialization() -> None:
    context = click.Context(click.Command("dbtalk"))

    with pytest.raises(RuntimeError, match="CLI context was not initialized"):
        dbtalk_context(context)


def test_main_invokes_root_command(monkeypatch: MonkeyPatch) -> None:
    called = False

    def fake_cli() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli_module, "cli", fake_cli)
    main()

    assert called
