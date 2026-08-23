"""Typed Dynaconf settings for database operations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf

DEFAULT_MYSQL_PORT = 3306
DEFAULT_OPERATION_TIMEOUT_SECONDS = 30
DEFAULT_POSTGRES_CLIENT_IMAGE = "postgres:18"
ENV_PREFIX = "DBTALK"
ENV_SELECTOR = f"{ENV_PREFIX}_ENVKEY"


@dataclass(frozen=True)
class LoggingSettings:
    level: str
    format: str


@dataclass(frozen=True)
class MySQLDumpConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    create_database: bool
    drop_database: bool
    output_directory: str


@dataclass(frozen=True)
class MySQLRestoreConfig:
    host: str
    port: int
    user: str
    password: str
    database: str = ""


@dataclass(frozen=True)
class DatabaseTransferConfig:
    zero_datetime_as_null: bool
    operation_timeout_seconds: int


@dataclass(frozen=True)
class PostgresConfig:
    output_directory: str
    client_image: str


@dataclass(frozen=True)
class Settings:
    verbose: bool
    logging: LoggingSettings
    mysqldump: MySQLDumpConfig
    mysqlrestore: MySQLRestoreConfig
    database: DatabaseTransferConfig
    postgres: PostgresConfig


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings(project_root: Path | None = None) -> Settings:
    """Load YAML, a selected dotenv file, and ``DBTALK_*`` overrides."""
    root = (project_root or default_project_root()).resolve()
    environment = os.environ.get(ENV_SELECTOR)
    dotenv_path = root / f".env.{environment}" if environment else None
    config = Dynaconf(
        settings_files=[str(root / "dbtalk.yaml")],
        envvar_prefix=ENV_PREFIX,
        load_dotenv=dotenv_path is not None,
        dotenv_path=str(dotenv_path) if dotenv_path else None,
        environments=False,
    )
    return Settings(
        verbose=bool_config(config.get("verbose", False)),
        logging=load_logging_settings(config.get("logging")),
        mysqldump=load_mysql_dump_config(config.get("mysqldump")),
        mysqlrestore=load_mysql_restore_config(config.get("mysqlrestore")),
        database=load_database_transfer_config(config.get("database")),
        postgres=load_postgres_config(config.get("postgres")),
    )


def mapping_config(value: Any) -> Mapping[str, object]:
    if value is None:
        return {}
    assert isinstance(value, Mapping)
    return value


def int_config(value: object) -> int:
    if isinstance(value, int):
        return value
    assert isinstance(value, str)
    return int(value)


def bool_config(value: object) -> bool:
    if isinstance(value, bool):
        return value
    assert isinstance(value, str)
    return value.lower() in {"1", "true", "yes", "on"}


def load_logging_settings(value: Any) -> LoggingSettings:
    config = mapping_config(value)
    level = config.get("level", "INFO")
    log_format = config.get("format", "%(levelname)s %(name)s: %(message)s")
    assert isinstance(level, str)
    assert isinstance(log_format, str)
    return LoggingSettings(level=level, format=log_format)


def load_mysql_dump_config(value: Any) -> MySQLDumpConfig:
    config = mapping_config(value)
    host = config.get("host", "localhost")
    user = config.get("user", "")
    password = config.get("password", "")
    database = config.get("database", "")
    output_directory = config.get("output_directory", "data")
    assert isinstance(host, str)
    assert isinstance(user, str)
    assert isinstance(password, str)
    assert isinstance(database, str)
    assert isinstance(output_directory, str)

    port = int_config(config.get("port", DEFAULT_MYSQL_PORT))
    if not host:
        raise ValueError("mysqldump.host must not be empty")
    if not 1 <= port <= 65535:
        raise ValueError("mysqldump.port must be between 1 and 65535")
    if not output_directory.strip():
        raise ValueError("mysqldump.output_directory must not be empty")
    return MySQLDumpConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        create_database=bool_config(config.get("create_database", False)),
        drop_database=bool_config(config.get("drop_database", False)),
        output_directory=output_directory,
    )


def load_mysql_restore_config(value: Any) -> MySQLRestoreConfig:
    config = mapping_config(value)
    host = config.get("host", "localhost")
    user = config.get("user", "")
    password = config.get("password", "")
    database = config.get("database", "")
    assert isinstance(host, str)
    assert isinstance(user, str)
    assert isinstance(password, str)
    assert isinstance(database, str)

    port = int_config(config.get("port", DEFAULT_MYSQL_PORT))
    if not host:
        raise ValueError("mysqlrestore.host must not be empty")
    if not 1 <= port <= 65535:
        raise ValueError("mysqlrestore.port must be between 1 and 65535")
    return MySQLRestoreConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )


def load_database_transfer_config(value: Any) -> DatabaseTransferConfig:
    config = mapping_config(value)
    timeout_seconds = int_config(
        config.get("operation_timeout_seconds", DEFAULT_OPERATION_TIMEOUT_SECONDS)
    )
    if timeout_seconds <= 0:
        raise ValueError("database.operation_timeout_seconds must be greater than zero")
    return DatabaseTransferConfig(
        zero_datetime_as_null=bool_config(config.get("zero_datetime_as_null", True)),
        operation_timeout_seconds=timeout_seconds,
    )


def load_postgres_config(value: Any) -> PostgresConfig:
    config = mapping_config(value)
    output_directory = config.get("output_directory", "data")
    client_image = config.get("client_image", DEFAULT_POSTGRES_CLIENT_IMAGE)
    assert isinstance(output_directory, str)
    assert isinstance(client_image, str)
    if not output_directory.strip():
        raise ValueError("postgres.output_directory must not be empty")
    if not client_image.strip():
        raise ValueError("postgres.client_image must not be empty")
    return PostgresConfig(
        output_directory=output_directory,
        client_image=client_image,
    )
