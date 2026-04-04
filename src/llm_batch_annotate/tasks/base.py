from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import RunConfig
from ..contracts.base import BaseMessageBuilder, BaseParser, BaseTask
from ..contracts.records import (
    AnnotationRecord,
    FailureRecord,
    GroupRecord,
    ParsedRequestRecord,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
    UnitRecord,
)
from ..enums import FailureKind, TaskKind
from ..grouping.fixed_size import plan_fixed_size_groups
from ..units.materialization import materialize_units as materialize_unit_records
from ..validation.coverage import coverage_failures, validate_coverage


class ComposedTaskBase(BaseTask):
    task_kind: TaskKind

    def __init__(
        self,
        *,
        required_input_columns: Sequence[str] | None = None,
        unit_id_column: str | None = None,
        unit_id_from_columns: Sequence[str] | None = None,
        unit_field_columns: Sequence[str] | None = None,
        unit_metadata_columns: Sequence[str] | None = None,
        group_id_prefix: str = "group",
        request_id_prefix: str = "request",
    ) -> None:
        self.required_input_columns = tuple(required_input_columns or ())
        self.unit_id_column = unit_id_column
        self.unit_id_from_columns = tuple(unit_id_from_columns or ())
        if self.unit_id_from_columns:
            msg = "unit_id_from_columns is no longer supported; configure source_input.row_id_column instead"
            raise ValueError(msg)
        self.unit_field_columns = tuple(unit_field_columns) if unit_field_columns is not None else None
        self.unit_metadata_columns = tuple(unit_metadata_columns or ())
        self.group_id_prefix = group_id_prefix
        self.request_id_prefix = request_id_prefix

    def validate_task_config(self, config: RunConfig) -> None:
        if config.task_kind is not self.task_kind:
            msg = f"{self.__class__.__name__} requires task_kind='{self.task_kind.value}'"
            raise ValueError(msg)
        if self.task_kind is TaskKind.GROUPED and config.grouping is None:
            msg = "grouped tasks require grouping configuration"
            raise ValueError(msg)
        if self.task_kind is TaskKind.SINGLE and config.grouping is not None:
            msg = "single tasks must not define grouping configuration"
            raise ValueError(msg)

    def _validate_source_rows(self, source_rows: Sequence[Mapping[str, Any]]) -> None:
        for row_index, row in enumerate(source_rows):
            missing_columns = [column for column in self.required_input_columns if column not in row]
            if missing_columns:
                missing_text = ", ".join(missing_columns)
                msg = f"source row {row_index} is missing required column(s): {missing_text}"
                raise ValueError(msg)

    def materialize_units(self, source_rows: Sequence[Mapping[str, Any]], config: RunConfig) -> Sequence[UnitRecord]:
        self.validate_task_config(config)
        self._validate_source_rows(source_rows)
        return materialize_unit_records(
            source_rows,
            row_id_column=self.unit_id_column or config.source_input.row_id_column,
            field_columns=self.unit_field_columns,
            metadata_columns=self.unit_metadata_columns,
        )

    def _group_context(self, group: GroupRecord) -> GroupRecord | None:
        if self.task_kind is TaskKind.GROUPED:
            return group
        return None

    def build_requests(
        self,
        units: Sequence[UnitRecord],
        groups: Sequence[GroupRecord],
        builder: BaseMessageBuilder,
        config: RunConfig,
    ) -> Sequence[RequestRecord]:
        units_by_id = {unit.unit_id: unit for unit in units}
        requests: list[RequestRecord] = []

        for request_index, group in enumerate(groups):
            group_units = [units_by_id[unit_id] for unit_id in group.unit_ids]
            payload = dict(builder.build_request_payload(group_units, self._group_context(group), config))
            row_ids = list(group.unit_ids)
            request_metadata = {
                "request_index": request_index,
                "group_id": group.group_id,
                "group_index": group.group_index,
                "row_id_column": config.source_input.row_id_column,
                "row_ids": row_ids,
                "unit_ids": row_ids,
            }
            payload_metadata = payload.get("metadata")
            if isinstance(payload_metadata, Mapping):
                request_metadata.update(dict(payload_metadata))
            request_metadata.setdefault("row_ids", row_ids)
            request_metadata.setdefault("unit_ids", row_ids)

            requests.append(
                RequestRecord(
                    request_id=(
                        row_ids[0]
                        if self.task_kind is TaskKind.SINGLE and len(row_ids) == 1
                        else f"{self.request_id_prefix}-{request_index:06d}"
                    ),
                    group_id=group.group_id,
                    unit_ids=row_ids,
                    payload=payload,
                    metadata=request_metadata,
                )
            )

        return requests

    def _raw_output_context(
        self,
        raw_output: RawOutputRecord,
        groups_by_id: Mapping[str, GroupRecord],
    ) -> tuple[str | None, list[str], dict[str, Any]]:
        metadata = dict(raw_output.metadata)
        payload_metadata = raw_output.payload.get("metadata")
        if isinstance(payload_metadata, Mapping):
            merged_metadata = dict(payload_metadata)
            merged_metadata.update(metadata)
            metadata = merged_metadata

        group_id = metadata.get("group_id")
        if group_id is not None:
            group_id = str(group_id)
        if group_id and group_id in groups_by_id:
            unit_ids = list(groups_by_id[group_id].unit_ids)
        else:
            raw_unit_ids = metadata.get("row_ids", metadata.get("unit_ids", []))
            unit_ids = [str(unit_id) for unit_id in raw_unit_ids]
        return group_id, unit_ids, metadata

    def parse_request_outputs(
        self,
        raw_outputs: Sequence[RawOutputRecord],
        raw_errors: Sequence[RawErrorRecord],
        parser: BaseParser,
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> tuple[Sequence[ParsedRequestRecord], Sequence[FailureRecord]]:
        groups_by_id = {group.group_id: group for group in groups}
        parsed_requests: list[ParsedRequestRecord] = []
        failures: list[FailureRecord] = []

        for raw_error in raw_errors:
            error_metadata = dict(raw_error.metadata)
            group_id = error_metadata.get("group_id")
            failures.append(
                parser.build_failure_record(
                    FailureKind.PROVIDER_EXECUTION,
                    raw_error.message,
                    request_id=raw_error.request_id,
                    group_id=str(group_id) if group_id is not None else None,
                    details={
                        "error_type": raw_error.error_type,
                        "payload": dict(raw_error.payload),
                        "metadata": error_metadata,
                    },
                )
            )

        for raw_output in raw_outputs:
            group_id, unit_ids, metadata = self._raw_output_context(raw_output, groups_by_id)
            try:
                payload = parser.extract_payload(raw_output, config)
                parsed_payload = dict(parser.deserialize_payload(payload, config))
                parser.validate_top_level(parsed_payload, config)
                parsed_requests.append(
                    ParsedRequestRecord(
                        request_id=raw_output.request_id,
                        group_id=group_id,
                        unit_ids=unit_ids,
                        parsed_payload=parsed_payload,
                        metadata={
                            "raw_output_status": raw_output.status.value,
                            **metadata,
                        },
                    )
                )
            except Exception as exc:
                failures.append(
                    parser.build_failure_record(
                        FailureKind.PARSE,
                        str(exc),
                        request_id=raw_output.request_id,
                        group_id=group_id,
                        details={"exception_type": type(exc).__name__},
                    )
                )

        return parsed_requests, failures

    def _expected_unit_ids_for_request(
        self,
        parsed_request: ParsedRequestRecord,
        groups_by_id: Mapping[str, GroupRecord],
    ) -> list[str]:
        if parsed_request.group_id is not None:
            group = groups_by_id.get(parsed_request.group_id)
            if group is None:
                msg = "parsed request references an unknown group_id during flattening"
                raise ValueError(msg)
            return list(group.unit_ids)
        if parsed_request.unit_ids:
            return list(parsed_request.unit_ids)
        msg = "parsed request is missing expected unit membership for flattening"
        raise ValueError(msg)

    def flatten_annotations_with_failures(
        self,
        parsed_requests: Sequence[ParsedRequestRecord],
        groups: Sequence[GroupRecord],
        parser: BaseParser,
        config: RunConfig,
    ) -> tuple[list[AnnotationRecord], list[FailureRecord]]:
        groups_by_id = {group.group_id: group for group in groups}
        annotations: list[AnnotationRecord] = []
        failures: list[FailureRecord] = []

        for parsed_request in parsed_requests:
            try:
                expected_unit_ids = self._expected_unit_ids_for_request(parsed_request, groups_by_id)
                flattened = list(parser.flatten_items(parsed_request, expected_unit_ids, config))
                normalized = list(parser.normalize_items(flattened, config))
                request_failures = list(parser.validate_coverage(normalized, expected_unit_ids, config))
            except Exception as exc:
                failures.append(
                    parser.build_failure_record(
                        FailureKind.FLATTEN,
                        str(exc),
                        request_id=parsed_request.request_id,
                        group_id=parsed_request.group_id,
                        details={"exception_type": type(exc).__name__},
                    )
                )
                continue

            annotations.extend(normalized)
            failures.extend(request_failures)

        return annotations, failures

    def flatten_annotations(
        self,
        parsed_requests: Sequence[ParsedRequestRecord],
        groups: Sequence[GroupRecord],
        parser: BaseParser,
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        annotations, failures = self.flatten_annotations_with_failures(parsed_requests, groups, parser, config)
        if failures:
            message = "; ".join(failure.message for failure in failures)
            raise ValueError(message)
        return annotations

    def normalize_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        del config
        return [
            AnnotationRecord(
                unit_id=annotation.unit_id,
                request_id=annotation.request_id,
                group_id=annotation.group_id,
                fields=dict(annotation.fields),
                metadata=dict(annotation.metadata),
            )
            for annotation in annotations
        ]

    def validate_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        expected_unit_ids = [unit_id for group in groups for unit_id in group.unit_ids]
        if not expected_unit_ids and not annotations:
            return []

        exact_coverage = True if config.grouping is None else config.grouping.exact_coverage
        result = validate_coverage(expected_unit_ids, annotations, exact_coverage=exact_coverage)
        failures = list(
            coverage_failures(
                result,
                failure_kind=FailureKind.VALIDATION,
                details={"scope": "final_annotations"},
            )
        )
        return failures


class SingleTaskBase(ComposedTaskBase):
    task_kind = TaskKind.SINGLE

    def plan_groups(self, units: Sequence[UnitRecord], config: RunConfig) -> Sequence[GroupRecord]:
        self.validate_task_config(config)
        return [
            GroupRecord(
                group_id=f"{self.group_id_prefix}-{group_index:06d}",
                unit_ids=[unit.unit_id],
                group_index=group_index,
                metadata={"unit_count": 1},
            )
            for group_index, unit in enumerate(units)
        ]


class GroupedTaskBase(ComposedTaskBase):
    task_kind = TaskKind.GROUPED

    def plan_groups(self, units: Sequence[UnitRecord], config: RunConfig) -> Sequence[GroupRecord]:
        self.validate_task_config(config)
        assert config.grouping is not None
        return plan_fixed_size_groups(
            units,
            config.grouping,
            group_id_prefix=self.group_id_prefix,
        )
