"""Schema compatibility and dependency rules for JSONL data imports."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import tzinfo

from .format import (
    MAX_DATETIME_FRACTIONAL_PRECISION,
    decode_value,
    type_family,
)
from .models import (
    DatabaseTransferError,
    JSONValue,
    TableBlock,
    TableBlockHeader,
    TableSchema,
    TransferMode,
    TransferPreview,
)


def validate_target_table(
    source: TableBlockHeader, target: TableSchema, mode: TransferMode
) -> None:
    """Validate one existing target table before any import writes occur."""

    if source.name != target.name:
        raise DatabaseTransferError("target table metadata does not match transfer file")
    target_columns = {column.name: column for column in target.columns}
    for source_column in source.columns:
        target_column = target_columns.get(source_column.name)
        if target_column is None:
            raise DatabaseTransferError(
                f"target table {source.name!r} is missing column {source_column.name!r}"
            )
        if not compatible_types(source_column.declared_type, target_column.declared_type):
            raise DatabaseTransferError(
                f"target table {source.name!r} column {source_column.name!r} "
                "has an incompatible type"
            )
    if source.primary_key != target.primary_key:
        raise DatabaseTransferError(
            f"target table {source.name!r} primary key does not match transfer file"
        )
    if mode == "upsert" and not source.primary_key:
        raise DatabaseTransferError(
            f"target table {source.name!r} has no primary key; use insert mode"
        )


def validate_import_rows(table: TableBlock, mode: TransferMode) -> None:
    """Reject upsert rows whose primary key cannot identify a target row."""

    if mode != "upsert":
        return
    primary_key_positions = _column_positions(table.header, table.header.primary_key)
    for row in table.rows:
        if any(row[position] is None for position in primary_key_positions):
            raise DatabaseTransferError(
                f"table {table.header.name!r} has an upsert row with a NULL primary key"
            )


def validate_import_row(
    row: tuple[JSONValue, ...],
    header: TableBlockHeader,
    mode: TransferMode,
    line_number: int,
) -> None:
    """Validate one row during streaming preflight."""

    if mode != "upsert":
        return
    positions = _column_positions(header, header.primary_key)
    if any(row[position] is None for position in positions):
        raise DatabaseTransferError(
            f"table {header.name!r} has an upsert row with a NULL primary key "
            f"at JSONL line {line_number}"
        )


def select_table_names(
    available: Mapping[str, object],
    include_tables: tuple[str, ...],
    exclude_tables: tuple[str, ...],
    description: str,
) -> tuple[str, ...]:
    """Resolve an explicit include set followed by an exclude set."""

    _validate_table_names(include_tables, available, description, "included")
    _validate_table_names(exclude_tables, available, description, "excluded")
    candidates = set(include_tables) if include_tables else set(available)
    selected = candidates - set(exclude_tables)
    if not selected:
        raise DatabaseTransferError("selected table set is empty")
    return tuple(name for name in available if name in selected)


def select_table_schemas(
    schemas: Mapping[str, TableSchema],
    include_tables: tuple[str, ...],
    exclude_tables: tuple[str, ...],
) -> dict[str, TableSchema]:
    names = select_table_names(schemas, include_tables, exclude_tables, "source database")
    selected = {name: schemas[name] for name in names}
    validate_selected_foreign_keys(selected)
    return selected


def select_transfer_preview(
    preview: TransferPreview,
    include_tables: tuple[str, ...],
    exclude_tables: tuple[str, ...],
) -> TransferPreview:
    available = {table.header.name: table for table in preview.tables}
    names = select_table_names(available, include_tables, exclude_tables, "transfer file")
    return TransferPreview(
        header=preview.header,
        tables=tuple(available[name] for name in names),
    )


def validate_selected_foreign_keys(schemas: Mapping[str, TableSchema]) -> None:
    selected = set(schemas)
    for schema in schemas.values():
        external = sorted(parent for parent in schema.foreign_keys if parent not in selected)
        if external:
            parents = ", ".join(repr(parent) for parent in external)
            raise DatabaseTransferError(
                f"table {schema.name!r} depends on unselected foreign-key table(s): {parents}"
            )


def order_table_blocks(
    tables: tuple[TableBlock, ...], schemas: dict[str, TableSchema]
) -> tuple[TableBlock, ...]:
    """Return parent-before-child table blocks or fail on an FK cycle."""

    blocks_by_name = {table.header.name: table for table in tables}
    remaining_dependencies = {
        name: {
            parent
            for parent in schemas[name].foreign_keys
            if parent in blocks_by_name and parent != name
        }
        for name in blocks_by_name
    }
    ready = sorted(name for name, parents in remaining_dependencies.items() if not parents)
    ordered_names: list[str] = []
    while ready:
        parent = ready.pop(0)
        ordered_names.append(parent)
        _release_children(parent, remaining_dependencies, ordered_names, ready)
    if len(ordered_names) != len(tables):
        raise DatabaseTransferError("foreign-key cycle prevents a safe table-by-table import")
    return tuple(blocks_by_name[name] for name in ordered_names)


def order_table_names(
    table_names: tuple[str, ...], schemas: Mapping[str, TableSchema]
) -> tuple[str, ...]:
    """Order selected table names without materializing row values."""

    validate_selected_foreign_keys({name: schemas[name] for name in table_names})
    remaining = {
        name: {
            parent
            for parent in schemas[name].foreign_keys
            if parent in table_names and parent != name
        }
        for name in table_names
    }
    ready = sorted(name for name, parents in remaining.items() if not parents)
    ordered: list[str] = []
    while ready:
        parent = ready.pop(0)
        ordered.append(parent)
        _release_children(parent, remaining, ordered, ready)
    if len(ordered) != len(table_names):
        raise DatabaseTransferError("foreign-key cycle prevents a safe table-by-table import")
    return tuple(ordered)


def table_block_values(
    table: TableBlock,
    target: TableSchema,
    target_timezone: tzinfo,
    default_datetime_precision: int | None,
) -> tuple[tuple[object, ...], ...]:
    """Decode a validated table block for one target schema and driver policy."""

    target_columns = {column.name: column for column in target.columns}
    return tuple(
        tuple(
            decode_value(
                value,
                target_columns[column.name].declared_type,
                target_timezone,
                _datetime_precision(
                    target_columns[column.name].declared_type,
                    default_datetime_precision,
                ),
            )
            for value, column in zip(row, table.header.columns, strict=True)
        )
        for row in table.rows
    )


def table_row_values(
    row: tuple[JSONValue, ...],
    header: TableBlockHeader,
    target: TableSchema,
    target_timezone: tzinfo,
    default_datetime_precision: int | None,
) -> tuple[object, ...]:
    """Decode one JSONL row for a target schema."""

    target_columns = {column.name: column for column in target.columns}
    return tuple(
        decode_value(
            value,
            target_columns[column.name].declared_type,
            target_timezone,
            _datetime_precision(
                target_columns[column.name].declared_type,
                default_datetime_precision,
            ),
        )
        for value, column in zip(row, header.columns, strict=True)
    )


def compatible_types(source_type: str, target_type: str) -> bool:
    """Accept compatible cross-engine declaration families conservatively."""

    source_family = type_family(source_type)
    target_family = type_family(target_type)
    if "unknown" in (source_family, target_family):
        return source_type.upper().strip() == target_type.upper().strip()
    if source_family == target_family:
        return True
    numeric_families = {"integer", "real", "decimal", "boolean"}
    return source_family in numeric_families and target_family in numeric_families


def _column_positions(header: TableBlockHeader, names: tuple[str, ...]) -> list[int]:
    positions = {column.name: position for position, column in enumerate(header.columns)}
    return [positions[name] for name in names]


def _validate_table_names(
    table_names: tuple[str, ...],
    available: Mapping[str, object],
    source_description: str,
    label: str,
) -> frozenset[str]:
    names = frozenset(table_names)
    if any(not name or "\x00" in name for name in names):
        raise DatabaseTransferError(f"{label} table names must not be empty or contain NUL")
    missing = sorted(names - available.keys())
    if missing:
        formatted = ", ".join(repr(name) for name in missing)
        raise DatabaseTransferError(
            f"{label} table(s) do not exist in {source_description}: {formatted}"
        )
    return names


def _release_children(
    parent: str,
    dependencies: dict[str, set[str]],
    ordered_names: list[str],
    ready: list[str],
) -> None:
    for child in sorted(dependencies):
        if parent not in dependencies[child]:
            continue
        dependencies[child].remove(parent)
        if not dependencies[child] and child not in ordered_names:
            ready.append(child)
    ready.sort()


def _datetime_precision(declared_type: str, default: int | None) -> int | None:
    if type_family(declared_type) != "datetime":
        return None
    match = re.search(
        rf"\b(?:DATETIME|TIMESTAMP)\s*\(\s*([0-{MAX_DATETIME_FRACTIONAL_PRECISION}])\s*\)",
        declared_type,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match is not None else default
