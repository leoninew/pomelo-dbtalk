"""SQLAlchemy Core adapter for SQLite, MySQL and PostgreSQL JSONL transfer."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import text

from .dsn import ParsedDsn, dsn_from_environment, parse_dsn
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
    TransferConnection,
    TransferHeader,
    TransferSummary,
)
from .mysql import _mysql_time_of_day, _normalize_mysql_zero_date
from .schema import (
    order_table_names,
    select_table_schemas,
    select_transfer_preview,
    table_row_values,
    validate_import_row,
    validate_target_table,
)

logger = logging.getLogger("dbtalk")
BATCH_SIZE = 1000


def export_sqlalchemy(options: ExportOptions) -> TransferSummary:
    parsed = _connection_dsn(options.connection)
    engine = _create_engine(parsed)
    logger.info("database export connecting %s", parsed.display)
    try:
        with engine.connect() as connection:
            _prepare_connection(connection, parsed, read_only=True)
            schemas = select_table_schemas(
                _load_schemas(connection),
                options.include_tables,
                options.exclude_tables,
            )
            table_count = 0
            row_count = 0
            with open_document_writer(
                options.output,
                TransferHeader(TRANSFER_FORMAT, parsed.dialect),
            ) as writer:
                for schema in _ordered_schemas(schemas):
                    result = connection.exec_driver_sql(_select_sql(connection, schema))
                    written = writer.write_table(
                        TableBlockHeader(schema.name, schema.columns, schema.primary_key),
                        _encoded_rows(result, schema, options, parsed),
                    )
                    table_count += 1
                    row_count += written
                    logger.info(
                        "database export table completed dialect=%s table=%s rows=%d",
                        parsed.dialect,
                        schema.name,
                        written,
                    )
                writer.finish()
            connection.rollback()
            return TransferSummary(table_count, row_count)
    except DatabaseTransferError:
        raise
    except SQLAlchemyError as error:
        raise DatabaseTransferError(f"{parsed.dialect.capitalize()} export failed") from error
    finally:
        engine.dispose()


def import_sqlalchemy(options: ImportOptions) -> TransferSummary:
    parsed = _connection_dsn(options.connection)
    engine = _create_engine(parsed)
    logger.info("database import connecting %s mode=%s", parsed.display, options.mode)
    try:
        with engine.connect() as connection:
            _prepare_connection(connection, parsed, read_only=False)
            schemas = _load_schemas(connection)
            preview = scan_document(
                options.input,
                row_validator=lambda header, row, line: validate_import_row(
                    row, header, options.mode, line
                ),
            )
            if preview.header.source not in ("sqlite", "mysql", "postgresql"):
                raise DatabaseTransferError("JSONL source driver is invalid")
            selected = select_transfer_preview(
                preview,
                options.include_tables,
                options.exclude_tables,
            )
            selected_schemas: dict[str, TableSchema] = {}
            for table in selected.tables:
                target = schemas.get(table.header.name)
                if target is None:
                    raise DatabaseTransferError(
                        f"target table {table.header.name!r} does not exist"
                    )
                validate_target_table(table.header, target, options.mode)
                selected_schemas[table.header.name] = target
            ordered_names = order_table_names(
                tuple(table.header.name for table in selected.tables), schemas
            )
            if ordered_names != tuple(table.header.name for table in selected.tables):
                raise DatabaseTransferError(
                    "JSONL table order does not satisfy target foreign-key order"
                )

            connection.rollback()
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
                    parsed,
                )
                expected_index += 1
                logger.info(
                    "database import table completed dialect=%s table=%s rows=%d mode=%s",
                    parsed.dialect,
                    table_header.name,
                    written,
                    options.mode,
                )
            if expected_index != len(ordered_names):
                raise DatabaseTransferError("JSONL table replay is incomplete")
            _verify_database(connection, parsed)
            return TransferSummary(
                len(selected.tables), sum(table.row_count for table in selected.tables)
            )
    except DatabaseTransferError:
        raise
    except SQLAlchemyError as error:
        raise DatabaseTransferError(f"{parsed.dialect.capitalize()} import failed") from error
    finally:
        engine.dispose()


def _connection_dsn(connection: TransferConnection) -> ParsedDsn:
    if (connection.dsn is None) == (connection.dsn_env is None):
        raise DatabaseTransferError("provide exactly one of dsn or dsn_env")
    if connection.dsn is not None:
        parsed = parse_dsn(connection.dsn)
    else:
        parsed = dsn_from_environment(connection.dsn_env)
    if parsed.dialect != connection.driver:
        raise DatabaseTransferError(
            f"connection DSN dialect {parsed.dialect!r} does not match {connection.driver!r}"
        )
    return parsed


def _create_engine(parsed: ParsedDsn) -> Engine:
    try:
        from sqlalchemy import create_engine

        return create_engine(parsed.url)
    except SQLAlchemyError as error:
        raise DatabaseTransferError("database engine could not be created") from error


def _prepare_connection(connection: Connection, parsed: ParsedDsn, *, read_only: bool) -> None:
    try:
        if parsed.dialect == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        elif parsed.dialect == "mysql" and read_only:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    except SQLAlchemyError as error:
        raise DatabaseTransferError("database session could not be prepared") from error


def _load_schemas(connection: Connection) -> dict[str, TableSchema]:
    inspector = inspect(connection)
    schemas: dict[str, TableSchema] = {}
    try:
        for name in sorted(inspector.get_table_names()):
            columns = tuple(
                ColumnDefinition(str(column["name"]), str(column.get("type") or ""))
                for column in inspector.get_columns(name)
            )
            primary = inspector.get_pk_constraint(name).get("constrained_columns") or []
            foreign_keys: list[str] = []
            for foreign_key in inspector.get_foreign_keys(name):
                referenced = foreign_key.get("referred_table")
                if isinstance(referenced, str) and referenced not in foreign_keys:
                    foreign_keys.append(referenced)
            schemas[name] = TableSchema(
                name=name,
                columns=columns,
                primary_key=tuple(str(column) for column in primary),
                foreign_keys=tuple(foreign_keys),
            )
    except SQLAlchemyError as error:
        raise DatabaseTransferError("database schema inspection failed") from error
    return schemas


def _ordered_schemas(schemas: dict[str, TableSchema]) -> tuple[TableSchema, ...]:
    ordered_names = order_table_names(tuple(schemas), schemas)
    return tuple(schemas[name] for name in ordered_names)


def _select_sql(connection: Connection, schema: TableSchema) -> str:
    quoted_columns = ", ".join(
        _quote_identifier(connection, column.name) for column in schema.columns
    )
    return f"SELECT {quoted_columns} FROM {_quote_identifier(connection, schema.name)}"


def _encoded_rows(
    result: Any,
    schema: TableSchema,
    options: ExportOptions,
    parsed: ParsedDsn,
) -> Iterator[tuple[JSONValue, ...]]:
    while batch := result.fetchmany(BATCH_SIZE):
        for row in batch:
            values: list[object] = []
            for value, column in zip(row, schema.columns, strict=True):
                if parsed.dialect == "mysql":
                    value = _normalize_mysql_zero_date(value, column.declared_type, options)
                    if isinstance(value, timedelta):
                        value = _mysql_time_of_day(value)
                values.append(value)
            yield tuple(
                encode_value(value, column.declared_type, options.timezone)
                for value, column in zip(values, schema.columns, strict=True)
            )


def _import_table(
    connection: Connection,
    header: TableBlockHeader,
    rows: Iterator[tuple[JSONValue, ...]],
    target: TableSchema,
    options: ImportOptions,
    parsed: ParsedDsn,
) -> int:
    names = [column.name for column in header.columns]
    quoted_table = _quote_identifier(connection, header.name)
    quoted_columns = ", ".join(_quote_identifier(connection, name) for name in names)
    parameter_names = [f"value_{index}" for index in range(len(names))]
    placeholders = ", ".join(f":{name}" for name in parameter_names)
    insert_statement = text(
        f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
    )
    primary_key = header.primary_key
    key_positions = [names.index(name) for name in primary_key]
    written = 0
    try:
        with connection.begin():
            if options.mode == "insert":
                for row in rows:
                    values = _target_values(row, header, target, options, parsed)
                    connection.execute(insert_statement, _parameters(values, parameter_names))
                    written += 1
            else:
                non_primary = [name for name in names if name not in primary_key]
                update_positions = [names.index(name) for name in non_primary]
                where = " AND ".join(
                    f"{_quote_identifier(connection, name)} = :key_{index}"
                    for index, name in enumerate(primary_key)
                )
                exists_statement = text(f"SELECT 1 FROM {quoted_table} WHERE {where} LIMIT 1")
                update_statement = (
                    text(
                        f"UPDATE {quoted_table} SET "
                        + ", ".join(
                            f"{_quote_identifier(connection, name)} = :update_{index}"
                            for index, name in enumerate(non_primary)
                        )
                        + f" WHERE {where}"
                    )
                    if non_primary
                    else None
                )
                for row in rows:
                    values = _target_values(row, header, target, options, parsed)
                    keys = tuple(values[position] for position in key_positions)
                    key_parameters = {f"key_{index}": value for index, value in enumerate(keys)}
                    exists = connection.execute(exists_statement, key_parameters).first()
                    if exists is None:
                        connection.execute(insert_statement, _parameters(values, parameter_names))
                    elif update_statement is not None:
                        update_parameters = {
                            f"update_{index}": values[position]
                            for index, position in enumerate(update_positions)
                        }
                        connection.execute(
                            update_statement,
                            {**update_parameters, **key_parameters},
                        )
                    written += 1
    except SQLAlchemyError as error:
        raise DatabaseTransferError(
            f"{parsed.dialect.capitalize()} import failed for table {header.name!r}"
        ) from error
    return written


def _target_values(
    row: tuple[JSONValue, ...],
    header: TableBlockHeader,
    target: TableSchema,
    options: ImportOptions,
    parsed: ParsedDsn,
) -> tuple[object, ...]:
    default_precision = 0 if parsed.dialect == "mysql" else None
    values = table_row_values(row, header, target, options.timezone, default_precision)
    if parsed.dialect == "sqlite":
        return tuple(
            format(value, "f") if hasattr(value, "as_tuple") else value for value in values
        )
    return values


def _parameters(values: tuple[object, ...], names: list[str]) -> dict[str, object]:
    return dict(zip(names, values, strict=True))


def _quote_identifier(connection: Connection, identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise DatabaseTransferError("database identifier is invalid")
    return connection.dialect.identifier_preparer.quote(identifier)


def _verify_database(connection: Connection, parsed: ParsedDsn) -> None:
    if parsed.dialect != "sqlite":
        return
    try:
        integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
        if integrity != "ok":
            raise DatabaseTransferError("SQLite integrity_check failed")
        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise DatabaseTransferError("SQLite foreign_key_check failed")
    except SQLAlchemyError as error:
        raise DatabaseTransferError("SQLite integrity verification failed") from error


__all__ = ["export_sqlalchemy", "import_sqlalchemy"]
