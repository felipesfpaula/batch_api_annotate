from __future__ import annotations

from llm_batch_annotate import (
    AnnotationRecord,
    GroupRecord,
    coverage_failures,
    validate_coverage,
    validate_group_coverage,
)


def test_validate_coverage_accepts_exact_match() -> None:
    result = validate_coverage(["u-1", "u-2"], ["u-1", "u-2"], exact_coverage=True)

    assert result.valid is True
    assert result.missing_unit_ids == []
    assert result.unexpected_unit_ids == []
    assert result.duplicate_unit_ids == []


def test_validate_coverage_detects_duplicates_missing_and_unexpected() -> None:
    result = validate_coverage(["u-1", "u-2"], ["u-1", "u-1", "u-3"], exact_coverage=True)

    assert result.valid is False
    assert result.duplicate_unit_ids == ["u-1"]
    assert result.missing_unit_ids == ["u-2"]
    assert result.unexpected_unit_ids == ["u-3"]


def test_validate_coverage_allows_missing_when_not_exact() -> None:
    result = validate_coverage(["u-1", "u-2"], ["u-1"], exact_coverage=False)

    assert result.valid is True
    assert result.missing_unit_ids == ["u-2"]


def test_validate_group_coverage_uses_group_membership() -> None:
    group = GroupRecord(group_id="group-1", unit_ids=["u-1", "u-2"])
    annotations = [
        AnnotationRecord(unit_id="u-1", request_id="request-1", group_id="group-1"),
        AnnotationRecord(unit_id="u-2", request_id="request-1", group_id="group-1"),
    ]

    result = validate_group_coverage(group, annotations)

    assert result.valid is True
    assert result.expected_unit_ids == ["u-1", "u-2"]


def test_coverage_failures_emits_structured_failure_records() -> None:
    result = validate_coverage(["u-1", "u-2"], ["u-1", "u-1", "u-3"], exact_coverage=True)
    failures = coverage_failures(result, request_id="request-1", group_id="group-1")

    assert len(failures) == 3
    assert [failure.message for failure in failures] == [
        "duplicate unit_id values detected in coverage validation",
        "unexpected unit_id values detected in coverage validation",
        "missing expected unit_id values detected in coverage validation",
    ]
    assert all(failure.request_id == "request-1" for failure in failures)
