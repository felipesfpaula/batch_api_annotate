from __future__ import annotations

import pytest

from llm_batch_annotate import derive_unit_id, materialize_units


def test_materialize_units_uses_explicit_unit_id_column() -> None:
    units = materialize_units(
        [
            {"unit_id": "u-1", "query": "shoes", "source": "catalog"},
            {"unit_id": "u-2", "query": "boots", "source": "catalog"},
        ],
        unit_id_column="unit_id",
        metadata_columns=["source"],
    )

    assert [unit.unit_id for unit in units] == ["u-1", "u-2"]
    assert units[0].fields == {"query": "shoes"}
    assert units[0].metadata == {"source": "catalog"}


def test_materialize_units_can_derive_ids_from_columns() -> None:
    units = materialize_units(
        [{"query": "red shoes", "locale": "en-US"}],
        unit_id_from_columns=["query", "locale"],
    )

    assert units[0].unit_id.startswith("unit-")
    assert units[0].fields == {"query": "red shoes", "locale": "en-US"}


def test_derive_unit_id_falls_back_to_row_index() -> None:
    unit_id = derive_unit_id({"query": "red shoes"}, source_row_index=7)
    assert unit_id == "unit-000007"


def test_materialize_units_rejects_duplicate_unit_ids() -> None:
    with pytest.raises(ValueError, match="duplicate unit_id"):
        materialize_units(
            [
                {"unit_id": "u-1", "query": "shoes"},
                {"unit_id": "u-1", "query": "boots"},
            ],
            unit_id_column="unit_id",
        )


def test_materialize_units_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="missing required field"):
        materialize_units(
            [{"query": "shoes"}],
            field_columns=["query", "locale"],
        )
