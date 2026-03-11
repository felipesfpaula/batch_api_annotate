from __future__ import annotations

import hashlib
import json
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
    source_row_index: int | None = None,
    unit_id_column: str | None = None,
    unit_id_from_columns: Sequence[str] | None = None,
    prefix: str = "unit",
) -> str:
    if unit_id_column is not None:
        _require_columns(row, [unit_id_column], context="unit id")
        value = str(row[unit_id_column]).strip()
        if not value:
            msg = "unit_id values must be non-empty"
            raise ValueError(msg)
        return value

    if unit_id_from_columns:
        _require_columns(row, unit_id_from_columns, context="unit id derivation")
        payload = {column: row[column] for column in unit_id_from_columns}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}-{digest}"

    if source_row_index is None:
        msg = "source_row_index is required when no unit id strategy is provided"
        raise ValueError(msg)
    return f"{prefix}-{source_row_index:06d}"


def validate_unique_unit_ids(units: Sequence[UnitRecord]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []

    for unit in units:
        if unit.unit_id in seen and unit.unit_id not in duplicates:
            duplicates.append(unit.unit_id)
        seen.add(unit.unit_id)

    if duplicates:
        duplicates_text = ", ".join(duplicates)
        msg = f"duplicate unit_id values detected: {duplicates_text}"
        raise ValueError(msg)


def materialize_units(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    unit_id_column: str | None = None,
    unit_id_from_columns: Sequence[str] | None = None,
    field_columns: Sequence[str] | None = None,
    metadata_columns: Sequence[str] | None = None,
    unit_id_prefix: str = "unit",
) -> list[UnitRecord]:
    metadata_columns = list(metadata_columns or [])
    units: list[UnitRecord] = []

    for source_row_index, row in enumerate(source_rows):
        row_field_columns: list[str]
        if field_columns is None:
            excluded = set(metadata_columns)
            if unit_id_column is not None:
                excluded.add(unit_id_column)
            row_field_columns = [column for column in row if column not in excluded]
        else:
            row_field_columns = list(field_columns)

        _require_columns(row, row_field_columns, context="field")
        _require_columns(row, metadata_columns, context="metadata")

        unit_id = derive_unit_id(
            row,
            source_row_index=source_row_index,
            unit_id_column=unit_id_column,
            unit_id_from_columns=unit_id_from_columns,
            prefix=unit_id_prefix,
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
