from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import Field

from .._model import FrameworkModel
from ..contracts.records import AnnotationRecord, FailureRecord, GroupRecord
from ..enums import FailureKind


class CoverageValidationResult(FrameworkModel):
    expected_unit_ids: list[str] = Field(default_factory=list)
    observed_unit_ids: list[str] = Field(default_factory=list)
    exact_coverage: bool = True
    valid: bool = True
    duplicate_unit_ids: list[str] = Field(default_factory=list)
    missing_unit_ids: list[str] = Field(default_factory=list)
    unexpected_unit_ids: list[str] = Field(default_factory=list)


def _observed_unit_ids(items: Sequence[str] | Sequence[AnnotationRecord]) -> list[str]:
    unit_ids: list[str] = []
    for item in items:
        if isinstance(item, AnnotationRecord):
            unit_ids.append(item.unit_id)
        else:
            unit_ids.append(str(item))
    return unit_ids


def validate_coverage(
    expected_unit_ids: Sequence[str],
    observed_items: Sequence[str] | Sequence[AnnotationRecord],
    *,
    exact_coverage: bool = True,
) -> CoverageValidationResult:
    expected = list(expected_unit_ids)
    observed = _observed_unit_ids(observed_items)
    observed_counts = Counter(observed)

    duplicate_unit_ids = sorted(unit_id for unit_id, count in observed_counts.items() if count > 1)
    expected_set = set(expected)
    observed_set = set(observed)
    missing_unit_ids = sorted(expected_set - observed_set)
    unexpected_unit_ids = sorted(observed_set - expected_set)
    valid = not duplicate_unit_ids and not unexpected_unit_ids and (not exact_coverage or not missing_unit_ids)

    return CoverageValidationResult(
        expected_unit_ids=expected,
        observed_unit_ids=observed,
        exact_coverage=exact_coverage,
        valid=valid,
        duplicate_unit_ids=duplicate_unit_ids,
        missing_unit_ids=missing_unit_ids,
        unexpected_unit_ids=unexpected_unit_ids,
    )


def validate_group_coverage(
    group: GroupRecord,
    observed_items: Sequence[str] | Sequence[AnnotationRecord],
    *,
    exact_coverage: bool = True,
) -> CoverageValidationResult:
    return validate_coverage(group.unit_ids, observed_items, exact_coverage=exact_coverage)


def coverage_failures(
    result: CoverageValidationResult,
    *,
    request_id: str | None = None,
    group_id: str | None = None,
    failure_kind: FailureKind = FailureKind.VALIDATION,
    details: dict[str, Any] | None = None,
) -> list[FailureRecord]:
    base_details = dict(details or {})
    failures: list[FailureRecord] = []

    if result.duplicate_unit_ids:
        failures.append(
            FailureRecord(
                failure_kind=failure_kind,
                message="duplicate row id values detected in coverage validation",
                request_id=request_id,
                group_id=group_id,
                details={**base_details, "duplicate_unit_ids": result.duplicate_unit_ids},
            )
        )

    if result.unexpected_unit_ids:
        failures.append(
            FailureRecord(
                failure_kind=failure_kind,
                message="unexpected row id values detected in coverage validation",
                request_id=request_id,
                group_id=group_id,
                details={**base_details, "unexpected_unit_ids": result.unexpected_unit_ids},
            )
        )

    if result.exact_coverage and result.missing_unit_ids:
        failures.append(
            FailureRecord(
                failure_kind=failure_kind,
                message="missing expected row id values detected in coverage validation",
                request_id=request_id,
                group_id=group_id,
                details={**base_details, "missing_unit_ids": result.missing_unit_ids},
            )
        )

    return failures
