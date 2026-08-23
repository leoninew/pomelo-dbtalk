"""Tests for dbtalk configuration sources."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from dbtalk.settings import load_settings

DEFAULT_SETTINGS = """verbose: false
logging:
  level: INFO
  format: "%(levelname)s %(name)s: %(message)s"
mysqldump:
  host: localhost
  port: 3306
  user: ""
  password: ""
  database: ""
  create_database: false
  drop_database: false
  output_directory: data
mysqlrestore:
  host: localhost
  port: 3306
  user: ""
  password: ""
  database: ""
database:
  zero_datetime_as_null: true
  operation_timeout_seconds: 30
postgres:
  output_directory: data
  client_image: postgres:18
"""


@pytest.fixture(autouse=True)
def isolate_cli_environment() -> Iterator[None]:
    """Keep dotenv values loaded by Dynaconf from leaking across tests."""
    original = {
        key: value
        for key, value in os.environ.items()
        if key == "DBTALK_ENVKEY" or key.startswith("DBTALK_")
    }
    clear_cli_environment()
    try:
        yield
    finally:
        clear_cli_environment()
        os.environ.update(original)


def test_loads_yaml_settings(tmp_path: Path) -> None:
    write_settings(tmp_path)

    settings = load_settings(tmp_path)

    assert settings.mysqldump.host == "localhost"
    assert settings.mysqldump.port == 3306
    assert settings.mysqlrestore.database == ""
    assert settings.database.zero_datetime_as_null is True
    assert settings.database.operation_timeout_seconds == 30
    assert settings.postgres.output_directory == "data"
    assert settings.postgres.client_image == "postgres:18"
    assert settings.logging.level == "INFO"
    assert settings.logging.format == "%(levelname)s %(name)s: %(message)s"


def test_dotenv_overrides_yaml(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    write_settings(tmp_path)
    (tmp_path / ".env.local").write_text(
        "DBTALK_MYSQLDUMP__HOST=dotenv.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBTALK_ENVKEY", "local")

    settings = load_settings(tmp_path)

    assert settings.mysqldump.host == "dotenv.example.test"


def test_os_environment_overrides_dotenv(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    write_settings(tmp_path)
    (tmp_path / ".env.local").write_text(
        "DBTALK_MYSQLDUMP__HOST=dotenv.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBTALK_ENVKEY", "local")
    monkeypatch.setenv("DBTALK_MYSQLDUMP__HOST", "os.example.test")

    settings = load_settings(tmp_path)

    assert settings.mysqldump.host == "os.example.test"


def test_database_operation_timeout_can_be_overridden(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_settings(tmp_path)
    monkeypatch.setenv("DBTALK_DATABASE__OPERATION_TIMEOUT_SECONDS", "15")

    settings = load_settings(tmp_path)

    assert settings.database.operation_timeout_seconds == 15


def test_postgres_client_image_can_be_overridden(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    write_settings(tmp_path)
    monkeypatch.setenv("DBTALK_POSTGRES__CLIENT_IMAGE", "registry.example/postgres:19")

    settings = load_settings(tmp_path)

    assert settings.postgres.client_image == "registry.example/postgres:19"


def write_settings(path: Path) -> None:
    path.joinpath("dbtalk.yaml").write_text(DEFAULT_SETTINGS, encoding="utf-8")


def clear_cli_environment() -> None:
    for key in list(os.environ):
        if key.startswith("DBTALK_"):
            del os.environ[key]
