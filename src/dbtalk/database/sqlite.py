"""SQLite adapter for database-independent JSONL transfer."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from datetime import tzinfo
from decimal import Decimal
from pathlib import Path

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

logger = logging.getLogger("dbtalk")
BATCH_SIZE = 1000


def export_sqlite(options: ExportOptions) -> TransferSummary:
    path = _sqlite_path(options.connection.sqlite_path)
    logger.info("sqlite export opening path=%s", path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _verify_database(connection)
        connection.execute("BEGIN")
        schemas = _load_schemas(connection)
        schemas = select_table_schemas(schemas, options.include_tables, options.exclude_tables)
        logger.info(
            "sqlite export schema loaded path=%s tables=%d excluded=%d",
            path,
            len(schemas),
            len(options.exclude_tables),
        )
        table_count = 0
        row_count = 0
        with open_document_writer(
            options.output, TransferHeader(TRANSFER_FORMAT, "sqlite")
        ) as writer:
            for schema in _ordered_schemas(schemas):
                columns = [column.name for column in schema.columns]
                quoted_table = _quote_identifier(schema.name)
                cursor = connection.execute(
                    f"SELECT {', '.join(_quote_identifier(name) for name in columns)} "
                    f"FROM {quoted_table}"
                )

                written = writer.write_table(
                    TableBlockHeader(schema.name, schema.columns, schema.primary_key),
                    _encoded_rows(cursor, schema, options.timezone),
                )
                table_count += 1
                row_count += written
                logger.info(
                    "sqlite export table completed table=%s rows=%d",
                    schema.name,
                    written,
                )
            writer.finish()
        logger.info("sqlite export document written output=%s", options.output.resolve())
        connection.rollback()
        return TransferSummary(table_count, row_count)
    except DatabaseTransferError:
        connection.rollback()
        raise
    except sqlite3.Error as error:
        logger.error("sqlite export failed path=%s error=%s", path, error)
        raise DatabaseTransferError(f"SQLite export failed: {error}") from error
    finally:
        connection.close()


def import_sqlite(  # noqa: PLR0912, PLR0915
    options: ImportOptions,
) -> TransferSummary:
    path = _sqlite_path(options.connection.sqlite_path)
    logger.info("sqlite import opening path=%s", path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        schemas = _load_schemas(connection)
        logger.info("sqlite import schema loaded path=%s tables=%d", path, len(schemas))
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
            "sqlite import preflight completed mode=%s tables=%d",
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
                "sqlite import table completed table=%s rows=%d mode=%s",
                table_header.name,
                written,
                options.mode,
            )
        if expected_index != len(ordered_names):
            raise DatabaseTransferError("JSONL table replay is incomplete")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise DatabaseTransferError("SQLite integrity_check failed")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise DatabaseTransferError("SQLite foreign_key_check failed")
        logger.info("sqlite import integrity checks passed path=%s", path)
        return TransferSummary(
            len(selected.tables), sum(table.row_count for table in selected.tables)
        )
    except DatabaseTransferError:
        connection.rollback()
        raise
    except sqlite3.Error as error:
        logger.error("sqlite import failed path=%s error=%s", path, error)
        raise DatabaseTransferError(f"SQLite import failed: {error}") from error
    finally:
        connection.close()


def _import_table(
    connection: sqlite3.Connection,
    header: TableBlockHeader,
    rows: Iterator[tuple[JSONValue, ...]],
    target: TableSchema,
    options: ImportOptions,
) -> int:
    names = [column.name for column in header.columns]
    quoted_table = _quote_identifier(header.name)
    quoted_columns = ", ".join(_quote_identifier(name) for name in names)
    placeholders = ", ".join("?" for _ in names)
    written = 0
    try:
        connection.execute("BEGIN")
        if options.mode == "insert":
            statement = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
            for row in rows:
                values = tuple(
                    _sqlite_value(value)
                    for value in table_row_values(row, header, target, options.timezone, None)
                )
                connection.execute(statement, values)
                written += 1
        else:
            primary_key = header.primary_key
            non_primary = [name for name in names if name not in primary_key]
            where = " AND ".join(f"{_quote_identifier(name)} = ?" for name in primary_key)
            update = ", ".join(f"{_quote_identifier(name)} = ?" for name in non_primary)
            insert_statement = (
                f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
            )
            update_statement = (
                f"UPDATE {quoted_table} SET {update} WHERE {where}" if update else None
            )
            key_positions = [names.index(name) for name in primary_key]
            update_positions = [names.index(name) for name in non_primary]
            for row in rows:
                values = tuple(
                    _sqlite_value(value)
                    for value in table_row_values(row, header, target, options.timezone, None)
                )
                key_values = tuple(values[index] for index in key_positions)
                exists = connection.execute(
                    f"SELECT 1 FROM {quoted_table} WHERE {where} LIMIT 1", key_values
                ).fetchone()
                if exists and update_statement:
                    connection.execute(
                        update_statement,
                        tuple(values[index] for index in update_positions) + key_values,
                    )
                elif not exists:
                    connection.execute(insert_statement, values)
                written += 1
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise DatabaseTransferError(
            f"SQLite import failed for table {header.name!r}: {error}"
        ) from error
    return written


def _load_schemas(connection: sqlite3.Connection) -> dict[str, TableSchema]:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    schemas: dict[str, TableSchema] = {}
    for name in names:
        column_rows = connection.execute(f"PRAGMA table_info({_quote_identifier(name)})")
        columns = tuple(ColumnDefinition(str(row[1]), str(row[2] or "")) for row in column_rows)
        primary_key = tuple(
            str(row[1])
            for row in sorted(
                connection.execute(f"PRAGMA table_info({_quote_identifier(name)})"),
                key=lambda row: int(row[5]),
            )
            if int(row[5]) > 0
        )
        foreign_keys = tuple(
            str(row[2])
            for row in connection.execute(f"PRAGMA foreign_key_list({_quote_identifier(name)})")
        )
        schemas[name] = TableSchema(name, columns, primary_key, foreign_keys)
    return schemas


def _ordered_schemas(schemas: dict[str, TableSchema]) -> tuple[TableSchema, ...]:
    ordered_names = order_table_names(tuple(schemas), schemas)
    return tuple(schemas[name] for name in ordered_names)


def _sqlite_path(path: Path | None) -> Path:
    if path is None:
        raise DatabaseTransferError("--sqlite-path is required for SQLite")
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise DatabaseTransferError(f"SQLite database does not exist: {resolved}")
    return resolved


def _verify_database(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise DatabaseTransferError("SQLite integrity_check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DatabaseTransferError("SQLite foreign_key_check failed")


def _sqlite_value(value: object) -> object:
    return format(value, "f") if isinstance(value, Decimal) else value


def _encoded_rows(
    cursor: sqlite3.Cursor,
    schema: TableSchema,
    timezone: tzinfo,
) -> Iterator[tuple[JSONValue, ...]]:
    while batch := cursor.fetchmany(BATCH_SIZE):
        for row in batch:
            yield tuple(
                encode_value(value, column.declared_type, timezone)
                for value, column in zip(row, schema.columns, strict=True)
            )


def _quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise DatabaseTransferError("database identifier is invalid")
    return '"' + identifier.replace('"', '""') + '"'
