"""Public API and driver dispatch for SQLite/MySQL JSONL data transfer."""

from __future__ import annotations

import logging

from .format import (
    TRANSFER_FORMAT,
    decode_value,
    encode_value,
    format_datetime_for_database,
    iter_document_tables,
    normalize_datetime,
    read_jsonl,
    scan_document,
    type_family,
    write_document,
    write_jsonl,
)
from .models import (
    ColumnDefinition,
    DatabaseDriver,
    DatabaseTransferError,
    ExportOptions,
    ImportOptions,
    JSONScalar,
    JSONValue,
    TableBlock,
    TableBlockHeader,
    TablePreview,
    TableSchema,
    TransferConnection,
    TransferDocument,
    TransferHeader,
    TransferMode,
    TransferPreview,
    TransferSummary,
    TypedJSONValue,
)
from .mysql import export_mysql, import_mysql
from .schema import (
    compatible_types,
    order_table_blocks,
    table_block_values,
    validate_import_rows,
    validate_target_table,
)
from .sqlite import export_sqlite, import_sqlite

logger = logging.getLogger("dbtalk")


def export_database(options: ExportOptions) -> TransferSummary:
    """Export a database through the adapter selected by the source driver."""

    logger.info(
        "database export started driver=%s output=%s excluded=%d",
        options.connection.driver,
        options.output.resolve(),
        len(options.exclude_tables),
    )
    try:
        validate_connection(options.connection)
        exporters = {"sqlite": export_sqlite, "mysql": export_mysql}
        summary = exporters[options.connection.driver](options)
    except DatabaseTransferError as error:
        logger.error(
            "database export failed driver=%s output=%s error=%s",
            options.connection.driver,
            options.output.resolve(),
            error,
            exc_info=False,
        )
        raise
    logger.info(
        "database export completed driver=%s output=%s tables=%d rows=%d",
        options.connection.driver,
        options.output.resolve(),
        summary.table_count,
        summary.row_count,
    )
    return summary


def import_database(options: ImportOptions) -> TransferSummary:
    """Preflight and import one JSONL transfer document."""

    logger.info(
        "database import started driver=%s input=%s mode=%s excluded=%d",
        options.connection.driver,
        options.input.resolve(),
        options.mode,
        len(options.exclude_tables),
    )
    try:
        validate_connection(options.connection)
        importers = {"sqlite": import_sqlite, "mysql": import_mysql}
        summary = importers[options.connection.driver](options)
    except DatabaseTransferError as error:
        logger.error(
            "database import failed driver=%s input=%s mode=%s error=%s",
            options.connection.driver,
            options.input.resolve(),
            options.mode,
            error,
            exc_info=False,
        )
        raise
    logger.info(
        "database import completed driver=%s input=%s mode=%s tables=%d rows=%d",
        options.connection.driver,
        options.input.resolve(),
        options.mode,
        summary.table_count,
        summary.row_count,
    )
    return summary


def validate_connection(connection: TransferConnection) -> None:
    """Validate the driver-specific CLI connection input before execution."""

    if connection.driver == "sqlite" and connection.sqlite_path is None:
        raise DatabaseTransferError("--sqlite-path is required for SQLite")
    if connection.driver == "mysql" and not connection.mysql_dsn_env:
        raise DatabaseTransferError("--mysql-dsn-env is required for MySQL")


__all__ = [
    "TRANSFER_FORMAT",
    "ColumnDefinition",
    "DatabaseDriver",
    "DatabaseTransferError",
    "ExportOptions",
    "ImportOptions",
    "JSONScalar",
    "JSONValue",
    "TableBlock",
    "TableBlockHeader",
    "TablePreview",
    "TableSchema",
    "TransferConnection",
    "TransferDocument",
    "TransferHeader",
    "TransferMode",
    "TransferPreview",
    "TransferSummary",
    "TypedJSONValue",
    "compatible_types",
    "decode_value",
    "encode_value",
    "export_database",
    "format_datetime_for_database",
    "import_database",
    "iter_document_tables",
    "normalize_datetime",
    "order_table_blocks",
    "read_jsonl",
    "scan_document",
    "table_block_values",
    "type_family",
    "validate_connection",
    "validate_import_rows",
    "validate_target_table",
    "write_document",
    "write_jsonl",
]
