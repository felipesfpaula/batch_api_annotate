from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..contracts.records import UnitRecord


def _require_columns(row: Mapping[str, Any], columns: Sequence[str], *, context: str) -> None:
    missing = [column for column in columns if column not in row]
    if missing:
        missing_text = ", ".join(missing)
        msg = f"missing required {context} column(s): {missing_text}"
        raise ValueError(msg)


def derive_unit_id(
    row: Mapping[str, Any],
    *,
    row_id_column: str,
) -> str:
    _require_columns(row, [row_id_column], context="row id")
    value = str(row[row_id_column]).strip()
    if not value:
        msg = "row id values must be non-empty"
        raise ValueError(msg)
    return value


def validate_unique_unit_ids(units: Sequence[UnitRecord]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []

    for unit in units:
        if unit.unit_id in seen and unit.unit_id not in duplicates:
            duplicates.append(unit.unit_id)
        seen.add(unit.unit_id)

    if duplicates:
        duplicates_text = ", ".join(duplicates)
        msg = f"duplicate row id values detected: {duplicates_text}"
        raise ValueError(msg)


def materialize_units(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    row_id_column: str,
    field_columns: Sequence[str] | None = None,
    metadata_columns: Sequence[str] | None = None,
) -> list[UnitRecord]:
    metadata_columns = list(metadata_columns or [])
    units: list[UnitRecord] = []

    for source_row_index, row in enumerate(source_rows):
        row_field_columns: list[str]
        if field_columns is None:
            excluded = set(metadata_columns)
            excluded.add(row_id_column)
            row_field_columns = [column for column in row if column not in excluded]
        else:
            row_field_columns = list(field_columns)

        _require_columns(row, row_field_columns, context="field")
        _require_columns(row, metadata_columns, context="metadata")

        unit_id = derive_unit_id(
            row,
            row_id_column=row_id_column,
        )

        fields = {column: row[column] for column in row_field_columns}
        metadata = {column: row[column] for column in metadata_columns}
        units.append(
            UnitRecord(
                unit_id=unit_id,
                source_row_index=source_row_index,
                fields=fields,
                metadata=metadata,
            )
        )

    validate_unique_unit_ids(units)
    return units
