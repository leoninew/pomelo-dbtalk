"""PyMySQL adapter for database-independent JSONL transfer."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pymysql

from .format import (
    TRANSFER_FORMAT,
    encode_value,
    iter_document_tables,
    open_document_writer,
    scan_document,
)
from .models import (
    ColumnDefinition,
    DatabaseTransferError,
    ExportOptions,
    ImportOptions,
    JSONValue,
    TableBlockHeader,
    TableSchema,
    TransferHeader,
    TransferSummary,
)
from .schema import (
    order_table_names,
    select_table_schemas,
    select_transfer_preview,
    table_row_values,
    validate_import_row,
    validate_target_table,
)

_GO_DSN = re.compile(
    r"^(?P<user>[^:/@]+)(?::(?P<password>[^@]*))?@tcp\((?P<host>[^:)]+)(?::(?P<port>\d+))?\)/(?P<database>[^?]*)\??(?P<query>.*)$"
)
MAX_MYSQL_PORT = 65535
_MYSQL_ZERO_DATE = re.compile(r"0000-00-00(?: 00:00:00(?:\.\d{1,6})?)?")
_MYSQL_ZERO_DATE_TYPES = frozenset({"DATE", "DATETIME", "TIMESTAMP"})
logger = logging.getLogger("dbtalk")
BATCH_SIZE = 1000


@dataclass(frozen=True)
class MysqlDsn:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"


def export_mysql(options: ExportOptions) -> TransferSummary:
    dsn = load_dsn(options.connection.mysql_dsn_env)
    logger.info(
        "mysql export connecting host=%s port=%d database=%s",
        dsn.host,
        dsn.port,
        dsn.database,
    )
    connection = _connect(dsn)
    try:
        _begin_consistent_read(connection)
        schemas = _load_schemas(connection, dsn.database)
        schemas = select_table_schemas(schemas, options.include_tables, options.exclude_tables)
        logger.info(
            "mysql export schema loaded database=%s tables=%d excluded=%d",
            dsn.database,
            len(schemas),
            len(options.exclude_tables),
        )
        table_count = 0
        row_count = 0
        with open_document_writer(
            options.output, TransferHeader(TRANSFER_FORMAT, "mysql")
        ) as writer:
            for schema in _ordered_schemas(schemas):
                names = [column.name for column in schema.columns]
                query = (
                    f"SELECT {', '.join(_quote_identifier(name) for name in names)} "
                    f"FROM {_quote_identifier(schema.name)}"
                )
                with connection.cursor(pymysql.cursors.SSCursor) as cursor:
                    cursor.execute(query)

                    written = writer.write_table(
                        TableBlockHeader(schema.name, schema.columns, schema.primary_key),
                        _encoded_rows(cursor, schema, options),
                    )
                table_count += 1
                row_count += written
                logger.info(
                    "mysql export table completed table=%s rows=%d",
                    schema.name,
                    written,
                )
            writer.finish()
        connection.commit()
        logger.info("mysql export document written output=%s", options.output.resolve())
        return TransferSummary(table_count, row_count)
    except DatabaseTransferError:
        connection.rollback()
        raise
    except pymysql.MySQLError as error:
        logger.error(
            "mysql export failed host=%s port=%d database=%s",
            dsn.host,
            dsn.port,
            dsn.database,
            exc_info=False,
        )
        connection.rollback()
        raise DatabaseTransferError(f"MySQL export failed: {error}") from error
    finally:
        connection.close()


def import_mysql(options: ImportOptions) -> TransferSummary:
    dsn = load_dsn(options.connection.mysql_dsn_env)
    logger.info(
        "mysql import connecting host=%s port=%d database=%s mode=%s",
        dsn.host,
        dsn.port,
        dsn.database,
        options.mode,
    )
    connection = _connect(dsn)
    try:
        schemas = _load_schemas(connection, dsn.database)
        logger.info(
            "mysql import schema loaded database=%s tables=%d",
            dsn.database,
            len(schemas),
        )
        preview = scan_document(
            options.input,
            row_validator=lambda header, row, line: validate_import_row(
                row, header, options.mode, line
            ),
        )
        if preview.header.source not in ("sqlite", "mysql"):
            raise DatabaseTransferError("JSONL source driver is invalid")
        logger.info(
            "database import document loaded source=%s tables=%d rows=%d",
            preview.header.source,
            len(preview.tables),
            sum(table.row_count for table in preview.tables),
        )
        selected = select_transfer_preview(preview, options.include_tables, options.exclude_tables)
        selected_schemas: dict[str, TableSchema] = {}
        for table in selected.tables:
            target = schemas.get(table.header.name)
            if target is None:
                raise DatabaseTransferError(f"target table {table.header.name!r} does not exist")
            validate_target_table(table.header, target, options.mode)
            selected_schemas[table.header.name] = target
        ordered_names = order_table_names(
            tuple(table.header.name for table in selected.tables), schemas
        )
        if ordered_names != tuple(table.header.name for table in selected.tables):
            raise DatabaseTransferError(
                "JSONL table order does not satisfy target foreign-key order"
            )
        logger.info(
            "database import tables selected tables=%d rows=%d excluded=%d",
            len(selected.tables),
            sum(table.row_count for table in selected.tables),
            len(options.exclude_tables),
        )
        logger.info(
            "mysql import preflight completed mode=%s tables=%d",
            options.mode,
            len(selected.tables),
        )
        selected_names = set(ordered_names)
        expected_index = 0
        for _, table_header, rows in iter_document_tables(options.input):
            if table_header.name not in selected_names:
                for _ in rows:
                    pass
                continue
            if table_header.name != ordered_names[expected_index]:
                raise DatabaseTransferError(
                    "JSONL table order changed between preflight and import"
                )
            written = _import_table(
                connection,
                table_header,
                rows,
                selected_schemas[table_header.name],
                options,
            )
            expected_index += 1
            logger.info(
                "mysql import table completed table=%s rows=%d mode=%s",
                table_header.name,
                written,
                options.mode,
            )
        if expected_index != len(ordered_names):
            raise DatabaseTransferError("JSONL table replay is incomplete")
        return TransferSummary(
            len(selected.tables), sum(table.row_count for table in selected.tables)
        )
    except DatabaseTransferError:
        connection.rollback()
        raise
    except pymysql.MySQLError as error:
        logger.error(
            "mysql import failed host=%s port=%d database=%s mode=%s",
            dsn.host,
            dsn.port,
            dsn.database,
            options.mode,
            exc_info=False,
        )
        connection.rollback()
        raise DatabaseTransferError(f"MySQL import failed: {error}") from error
    finally:
        connection.close()


def load_dsn(environment_name: str | None) -> MysqlDsn:
    if not environment_name:
        raise DatabaseTransferError("--mysql-dsn-env is required for MySQL")
    raw = os.environ.get(environment_name)
    if not raw:
        raise DatabaseTransferError("MySQL DSN environment variable is not set")
    go_match = _GO_DSN.match(raw)
    if go_match:
        values = go_match.groupdict()
        query = parse_qs(values.get("query", ""))
        dsn = MysqlDsn(
            host=values["host"],
            port=int(values.get("port") or 3306),
            user=unquote(values["user"]),
            password=unquote(values.get("password") or ""),
            database=unquote(values["database"]),
            charset=(query.get("charset") or ["utf8mb4"])[0],
        )
        _validate_dsn(dsn)
        return dsn
    parsed = urlparse(raw)
    if parsed.scheme not in ("mysql", "mysql+pymysql") or not parsed.hostname:
        raise DatabaseTransferError("MySQL DSN must use mysql:// or Go tcp(...) syntax")
    if not parsed.path.strip("/"):
        raise DatabaseTransferError("MySQL DSN must include a database name")
    query = parse_qs(parsed.query)
    try:
        port = parsed.port or 3306
    except ValueError as error:
        raise DatabaseTransferError("MySQL DSN port is invalid") from error
    dsn = MysqlDsn(
        host=parsed.hostname,
        port=port,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=unquote(parsed.path.lstrip("/")),
        charset=(query.get("charset") or ["utf8mb4"])[0],
    )
    _validate_dsn(dsn)
    return dsn


def _connect(dsn: MysqlDsn) -> pymysql.connections.Connection:
    try:
        return pymysql.connect(
            host=dsn.host,
            port=dsn.port,
            user=dsn.user,
            password=dsn.password,
            database=dsn.database,
            charset=dsn.charset,
            autocommit=False,
        )
    except pymysql.MySQLError as error:
        raise DatabaseTransferError(f"MySQL connection failed: {error}") from error


def _load_schemas(
    connection: pymysql.connections.Connection, database: str
) -> dict[str, TableSchema]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT columns.TABLE_NAME, columns.COLUMN_NAME, columns.COLUMN_TYPE "
            "FROM information_schema.COLUMNS AS columns "
            "JOIN information_schema.TABLES AS tables "
            "ON tables.TABLE_SCHEMA = columns.TABLE_SCHEMA "
            "AND tables.TABLE_NAME = columns.TABLE_NAME "
            "WHERE columns.TABLE_SCHEMA = %s AND tables.TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY columns.TABLE_NAME, columns.ORDINAL_POSITION",
            (database,),
        )
        column_rows = cursor.fetchall()
        cursor.execute(
            "SELECT TABLE_NAME, COLUMN_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = %s AND CONSTRAINT_NAME = 'PRIMARY' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (database,),
        )
        primary_rows = cursor.fetchall()
        cursor.execute(
            "SELECT TABLE_NAME, REFERENCED_TABLE_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (database,),
        )
        foreign_rows = cursor.fetchall()
    columns_by_table: dict[str, list[ColumnDefinition]] = {}
    for table, column, declared_type in column_rows:
        columns_by_table.setdefault(str(table), []).append(
            ColumnDefinition(str(column), str(declared_type or ""))
        )
    primary_by_table: dict[str, list[str]] = {}
    for table, column in primary_rows:
        primary_by_table.setdefault(str(table), []).append(str(column))
    foreign_by_table: dict[str, list[str]] = {}
    for table, referenced_table in foreign_rows:
        foreign_by_table.setdefault(str(table), []).append(str(referenced_table))
    return {
        table: TableSchema(
            table,
            tuple(columns),
            tuple(primary_by_table.get(table, [])),
            tuple(foreign_by_table.get(table, [])),
        )
        for table, columns in columns_by_table.items()
    }


def _ordered_schemas(schemas: dict[str, TableSchema]) -> tuple[TableSchema, ...]:
    ordered_names = order_table_names(tuple(schemas), schemas)
    return tuple(schemas[name] for name in ordered_names)


def _import_table(
    connection: pymysql.connections.Connection,
    header: TableBlockHeader,
    rows: Iterator[tuple[JSONValue, ...]],
    target: TableSchema,
    options: ImportOptions,
) -> int:
    names = [column.name for column in header.columns]
    quoted_table = _quote_identifier(header.name)
    quoted_columns = ", ".join(_quote_identifier(name) for name in names)
    placeholders = ", ".join("%s" for _ in names)
    written = 0
    try:
        connection.begin()
        if options.mode == "insert":
            statement = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
            with connection.cursor() as cursor:
                for row in rows:
                    values = table_row_values(row, header, target, options.timezone, 0)
                    cursor.execute(statement, values)
                    written += 1
        else:
            primary_key = header.primary_key
            non_primary = [name for name in names if name not in primary_key]
            where = " AND ".join(f"{_quote_identifier(name)} = %s" for name in primary_key)
            key_positions = [names.index(name) for name in primary_key]
            update_positions = [names.index(name) for name in non_primary]
            insert_statement = (
                f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
            )
            update_statement = (
                f"UPDATE {quoted_table} SET "
                + ", ".join(f"{_quote_identifier(name)} = %s" for name in non_primary)
                + f" WHERE {where}"
                if non_primary
                else None
            )
            with connection.cursor() as cursor:
                for row in rows:
                    values = table_row_values(row, header, target, options.timezone, 0)
                    key_values = tuple(values[index] for index in key_positions)
                    cursor.execute(
                        f"SELECT 1 FROM {quoted_table} WHERE {where} LIMIT 1",
                        key_values,
                    )
                    if cursor.fetchone() is not None:
                        if update_statement:
                            cursor.execute(
                                update_statement,
                                tuple(values[index] for index in update_positions) + key_values,
                            )
                    else:
                        cursor.execute(insert_statement, values)
                    written += 1
        connection.commit()
    except pymysql.MySQLError as error:
        connection.rollback()
        raise DatabaseTransferError(
            f"MySQL import failed for table {header.name!r}: {error}"
        ) from error
    return written


def _encode_mysql_value(value: object, declared_type: str, options: ExportOptions) -> JSONValue:
    value = _normalize_mysql_zero_date(value, declared_type, options)
    if isinstance(value, timedelta):
        value = _mysql_time_of_day(value)
    return encode_value(value, declared_type, options.timezone)


def _normalize_mysql_zero_date(value: object, declared_type: str, options: ExportOptions) -> object:
    """Normalize MySQL zero dates only when the export policy allows it."""

    base_type = declared_type.upper().strip().split("(", maxsplit=1)[0].strip()
    if (
        not isinstance(value, str)
        or base_type not in _MYSQL_ZERO_DATE_TYPES
        or _MYSQL_ZERO_DATE.fullmatch(value) is None
    ):
        return value
    if options.zero_datetime_as_null:
        return None
    raise DatabaseTransferError(
        "MySQL zero date cannot be exported while database.zero_datetime_as_null is disabled"
    )


def _begin_consistent_read(connection: pymysql.connections.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")


def _validate_dsn(dsn: MysqlDsn) -> None:
    if not dsn.user:
        raise DatabaseTransferError("MySQL DSN must include a user name")
    if not dsn.database:
        raise DatabaseTransferError("MySQL DSN must include a database name")
    if not 1 <= dsn.port <= MAX_MYSQL_PORT:
        raise DatabaseTransferError(f"MySQL DSN port must be between 1 and {MAX_MYSQL_PORT}")


def _mysql_time_of_day(value: timedelta) -> str:
    """Convert PyMySQL's MySQL TIME duration into an ISO time-of-day string."""

    if value < timedelta() or value >= timedelta(days=1):
        raise DatabaseTransferError("MySQL TIME value is outside the ISO 8601 time-of-day range")
    total_seconds = value.seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if value.microseconds:
        return f"{formatted}.{value.microseconds:06d}".rstrip("0")
    return formatted


def _encoded_rows(
    cursor: pymysql.cursors.SSCursor,
    schema: TableSchema,
    options: ExportOptions,
) -> Iterator[tuple[JSONValue, ...]]:
    while batch := cursor.fetchmany(BATCH_SIZE):
        for row in batch:
            yield tuple(
                _encode_mysql_value(value, column.declared_type, options)
                for value, column in zip(row, schema.columns, strict=True)
            )


def _quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise DatabaseTransferError("database identifier is invalid")
    return "`" + identifier.replace("`", "``") + "`"
