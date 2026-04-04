from __future__ import annotations

import pytest

from llm_batch_annotate import derive_unit_id, materialize_units


def test_materialize_units_uses_required_row_id_column() -> None:
    units = materialize_units(
        [
            {"query_id": "q-1", "query": "shoes", "source": "catalog"},
            {"query_id": "q-2", "query": "boots", "source": "catalog"},
        ],
        row_id_column="query_id",
        metadata_columns=["source"],
    )

    assert [unit.unit_id for unit in units] == ["q-1", "q-2"]
    assert units[0].fields == {"query": "shoes"}
    assert units[0].metadata == {"source": "catalog"}


def test_materialize_units_auto_field_selection_excludes_row_id_column() -> None:
    units = materialize_units(
        [{"query_id": "q-1", "query": "red shoes", "locale": "en-US"}],
        row_id_column="query_id",
    )

    assert units[0].fields == {"query": "red shoes", "locale": "en-US"}


def test_derive_unit_id_uses_configured_row_id_column() -> None:
    unit_id = derive_unit_id({"query_id": "q-7", "query": "red shoes"}, row_id_column="query_id")
    assert unit_id == "q-7"


def test_materialize_units_rejects_duplicate_row_ids() -> None:
    with pytest.raises(ValueError, match="duplicate row id"):
        materialize_units(
            [
                {"query_id": "q-1", "query": "shoes"},
                {"query_id": "q-1", "query": "boots"},
            ],
            row_id_column="query_id",
        )


def test_materialize_units_rejects_missing_row_id_column() -> None:
    with pytest.raises(ValueError, match="missing required row id column"):
        materialize_units(
            [{"query": "shoes"}],
            row_id_column="query_id",
        )


def test_materialize_units_rejects_empty_row_id_values() -> None:
    with pytest.raises(ValueError, match="row id values must be non-empty"):
        materialize_units(
            [{"query_id": "   ", "query": "shoes"}],
            row_id_column="query_id",
        )


def test_materialize_units_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="missing required field"):
        materialize_units(
            [{"query_id": "q-1", "query": "shoes"}],
            row_id_column="query_id",
            field_columns=["query", "locale"],
        )
