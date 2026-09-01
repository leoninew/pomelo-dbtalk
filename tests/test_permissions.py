from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from sqlalchemy.dialects.mysql import dialect as MysqlDialect
from sqlalchemy.dialects.postgresql import dialect as PostgreSQLDialect

import dbtalk.mysql.permissions as mysql_permissions
import dbtalk.mysql.user as mysql_user
import dbtalk.postgres.permissions as postgres_permissions
import dbtalk.postgres.role as postgres_role
from dbtalk.cli import cli
from dbtalk.database.dsn import parse_dsn


class Result:
    def __init__(self, columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
        self._columns = columns
        self._rows = rows

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class Connection:
    def __init__(self, dialect: Any, result: Result) -> None:
        self.dialect = dialect
        self.result = result
        self.statements: list[str] = []
        self.parameters: list[dict[str, object]] = []

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execution_options(self, **_: object) -> Connection:
        return self

    def execute(self, statement: object, parameters: dict[str, object]) -> Result:
        self.statements.append(str(statement))
        self.parameters.append(parameters)
        return self.result

    def exec_driver_sql(self, statement: str) -> Result:
        self.statements.append(statement)
        return self.result


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> Connection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def test_mysql_permissions_list_uses_global_and_database_native_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(MysqlDialect(), Result(("scope", "grantee"), [("global", "u")]))
    engine = Engine(connection)
    monkeypatch.setattr(mysql_user, "create_engine", lambda _: engine)

    result = mysql_permissions.list_permissions(
        parse_dsn("mysql+pymysql://admin:secret@db.example/app"),
        "app_user",
        "app.example",
        "app",
    )

    assert result[1] == (("global", "u"),)
    assert "SCHEMA_PRIVILEGES" in connection.statements[0]
    assert "TABLE_NAME" not in connection.statements[0]
    assert connection.parameters == [{"grantee": "'app_user'@'app.example'", "database": "app"}]
    assert engine.disposed


def test_mysql_permissions_show_without_resource_binds_show_grants_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(MysqlDialect(), Result(("Grants",), [("GRANT USAGE",)]))
    monkeypatch.setattr(mysql_user, "create_engine", lambda _: Engine(connection))

    mysql_permissions.show_permissions(
        parse_dsn("mysql+pymysql://admin:secret@db.example/app"), "app_user", "%"
    )

    assert connection.statements == ["SHOW GRANTS FOR :user@:host"]
    assert connection.parameters == [{"user": "app_user", "host": "%"}]


def test_postgres_permissions_show_dispatches_native_acl_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(
        PostgreSQLDialect(),  # type: ignore[no-untyped-call]
        Result(("grantee",), [("app_role",)]),
    )
    monkeypatch.setattr(postgres_role, "create_engine", lambda _: Engine(connection))

    result = postgres_permissions.show_permissions(
        parse_dsn("postgresql+psycopg://admin:secret@db.example/app"), "app_role", "app", "public"
    )

    assert result[1] == (("app_role",),)
    assert "aclexplode" in connection.statements[0]
    assert connection.parameters == [{"role": "app_role", "database": "app", "schema": "public"}]


@pytest.mark.parametrize(
    ("command", "missing"),
    [
        (
            ["mysql", "permissions", "list", "--dsn", "mysql+pymysql://a:p@h/app", "--host", "h"],
            "--user",
        ),
        (
            [
                "postgres",
                "permissions",
                "show",
                "--dsn",
                "postgresql+psycopg://a:p@h/app",
                "--role",
                "bad role",
            ],
            "role name",
        ),
    ],
)
def test_permissions_filters_validate_principal(
    command: list[str],
    missing: str,
) -> None:
    result = CliRunner().invoke(cli, command)

    assert result.exit_code != 0
    assert missing in result.output
    assert "secret" not in result.output
