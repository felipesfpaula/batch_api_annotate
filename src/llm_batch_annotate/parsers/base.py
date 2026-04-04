from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import RunConfig
from ..contracts.base import BaseParser
from ..contracts.records import AnnotationRecord, FailureRecord, GroupRecord, ParsedRequestRecord, RawOutputRecord
from ..enums import FailureKind, TaskKind
from ..validation.coverage import coverage_failures, validate_coverage


class BaseOutputParser(BaseParser):
    def __init__(
        self,
        *,
        item_list_fields: Sequence[str] | None = None,
        unit_id_field: str | None = None,
    ) -> None:
        self.item_list_fields = tuple(item_list_fields or ("items", "annotations", "results"))
        self.unit_id_field = unit_id_field

    def id_field_name(self, config: RunConfig) -> str:
        return self.unit_id_field or config.source_input.row_id_column

    def extract_payload(self, raw_output: RawOutputRecord, config: RunConfig) -> Mapping[str, Any]:
        del config
        return dict(raw_output.payload)

    def deserialize_payload(self, payload: Mapping[str, Any], config: RunConfig) -> Mapping[str, Any]:
        del config
        return dict(payload)

    def validate_top_level(self, parsed_payload: Mapping[str, Any], config: RunConfig) -> None:
        self.extract_items(parsed_payload, config)

    def extract_items(self, parsed_payload: Mapping[str, Any], config: RunConfig) -> list[dict[str, Any]]:
        id_field_name = self.id_field_name(config)
        if id_field_name in parsed_payload:
            raw_items: Any = [parsed_payload]
        else:
            raw_items = None
            for field_name in self.item_list_fields:
                if field_name in parsed_payload:
                    raw_items = parsed_payload[field_name]
                    break
            if raw_items is None and config.task_kind is TaskKind.SINGLE:
                raw_items = [parsed_payload]

        if raw_items is None:
            msg = f"parsed payload must contain a top-level '{id_field_name}' field or an item collection"
            raise ValueError(msg)

        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
            msg = "parsed annotation items must be a sequence of mappings"
            raise ValueError(msg)

        items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                msg = "parsed annotation items must be mappings"
                raise ValueError(msg)
            items.append(dict(raw_item))
        return items

    def build_annotation_record(
        self,
        item: Mapping[str, Any],
        parsed_request: ParsedRequestRecord,
        *,
        item_index: int,
        item_count: int,
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> AnnotationRecord:
        id_field_name = self.id_field_name(config)
        if id_field_name in item:
            unit_id = str(item.get(id_field_name, "")).strip()
            if not unit_id:
                msg = f"parsed item at index {item_index} has an empty '{id_field_name}'"
                raise ValueError(msg)
        elif config.task_kind is TaskKind.SINGLE and len(expected_unit_ids) == 1 and item_count == 1:
            unit_id = str(expected_unit_ids[0])
        elif config.task_kind is TaskKind.SINGLE and len(expected_unit_ids) == 1 and item_count > 1:
            msg = (
                f"parsed item at index {item_index} is missing '{id_field_name}' "
                "and unit inference is ambiguous when multiple items are returned"
            )
            raise ValueError(msg)
        else:
            msg = f"parsed item at index {item_index} is missing a non-empty '{id_field_name}'"
            raise ValueError(msg)

        raw_metadata = item.get("metadata", {})
        if raw_metadata is None:
            raw_metadata = {}
        if not isinstance(raw_metadata, Mapping):
            msg = "parsed item metadata must be a mapping"
            raise ValueError(msg)

        if "fields" in item:
            raw_fields = item["fields"]
            if not isinstance(raw_fields, Mapping):
                msg = "parsed item 'fields' must be a mapping when present"
                raise ValueError(msg)
            fields = {key: value for key, value in item.items() if key not in {id_field_name, "fields", "metadata"}}
            fields.update(dict(raw_fields))
        else:
            fields = {key: value for key, value in item.items() if key not in {id_field_name, "metadata"}}

        metadata = {"item_index": item_index}
        metadata.update(dict(raw_metadata))
        return AnnotationRecord(
            unit_id=unit_id,
            request_id=parsed_request.request_id,
            group_id=parsed_request.group_id,
            fields=fields,
            metadata=metadata,
        )

    def flatten_items(
        self,
        parsed_request: ParsedRequestRecord,
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        items = self.extract_items(parsed_request.parsed_payload, config)
        return [
            self.build_annotation_record(
                item,
                parsed_request,
                item_index=item_index,
                item_count=len(items),
                expected_unit_ids=expected_unit_ids,
                config=config,
            )
            for item_index, item in enumerate(items)
        ]

    def validate_coverage(
        self,
        items: Sequence[AnnotationRecord],
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        exact_coverage = True if config.grouping is None else config.grouping.exact_coverage
        request_id = items[0].request_id if items else None
        group_id = items[0].group_id if items else None
        result = validate_coverage(expected_unit_ids, items, exact_coverage=exact_coverage)
        return coverage_failures(
            result,
            request_id=request_id,
            group_id=group_id,
            failure_kind=FailureKind.VALIDATION,
            details={"expected_unit_ids": list(expected_unit_ids)},
        )

    def normalize_items(
        self,
        items: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        del config
        return [
            AnnotationRecord(
                unit_id=item.unit_id,
                request_id=item.request_id,
                group_id=item.group_id,
                fields=dict(item.fields),
                metadata=dict(item.metadata),
            )
            for item in items
        ]

    def build_failure_record(
        self,
        failure_kind: FailureKind,
        message: str,
        *,
        request_id: str | None = None,
        unit_id: str | None = None,
        group_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> FailureRecord:
        return FailureRecord(
            failure_kind=failure_kind,
            message=message,
            request_id=request_id,
            unit_id=unit_id,
            group_id=group_id,
            details=dict(details or {"parser": self.__class__.__name__}),
        )

    def failure_from_exception(
        self,
        failure_kind: FailureKind,
        exception: Exception,
        *,
        request_id: str | None = None,
        unit_id: str | None = None,
        group_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> FailureRecord:
        payload = {"exception_type": type(exception).__name__}
        payload.update(dict(details or {}))
        return self.build_failure_record(
            failure_kind,
            str(exception),
            request_id=request_id,
            unit_id=unit_id,
            group_id=group_id,
            details=payload,
        )

    def parse_output(
        self,
        raw_output: RawOutputRecord,
        config: RunConfig,
        *,
        group_id: str | None = None,
        unit_ids: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ParsedRequestRecord:
        payload = self.extract_payload(raw_output, config)
        parsed_payload = dict(self.deserialize_payload(payload, config))
        self.validate_top_level(parsed_payload, config)

        parsed_metadata = {"raw_output_status": raw_output.status.value}
        parsed_metadata.update(dict(raw_output.metadata))
        parsed_metadata.update(dict(metadata or {}))

        return ParsedRequestRecord(
            request_id=raw_output.request_id,
            group_id=group_id,
            unit_ids=list(unit_ids or []),
            parsed_payload=parsed_payload,
            metadata=parsed_metadata,
        )

    def parse_outputs(
        self,
        raw_outputs: Sequence[RawOutputRecord],
        config: RunConfig,
        *,
        request_context: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[list[ParsedRequestRecord], list[FailureRecord]]:
        parsed_requests: list[ParsedRequestRecord] = []
        failures: list[FailureRecord] = []
        context_lookup = dict(request_context or {})

        for raw_output in raw_outputs:
            context = context_lookup.get(raw_output.request_id, {})
            try:
                context_unit_ids = context.get("row_ids", context.get("unit_ids"))
                parsed_requests.append(
                    self.parse_output(
                        raw_output,
                        config,
                        group_id=context.get("group_id"),
                        unit_ids=context_unit_ids,
                        metadata=context.get("metadata"),
                    )
                )
            except Exception as exc:
                failures.append(
                    self.failure_from_exception(
                        FailureKind.PARSE,
                        exc,
                        request_id=raw_output.request_id,
                        group_id=context.get("group_id"),
                    )
                )

        return parsed_requests, failures

    def flatten_request(
        self,
        parsed_request: ParsedRequestRecord,
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> tuple[list[AnnotationRecord], list[FailureRecord]]:
        try:
            flattened = list(self.flatten_items(parsed_request, expected_unit_ids, config))
            normalized = list(self.normalize_items(flattened, config))
        except Exception as exc:
            return [], [
                self.failure_from_exception(
                    FailureKind.FLATTEN,
                    exc,
                    request_id=parsed_request.request_id,
                    group_id=parsed_request.group_id,
                    details={"expected_unit_ids": list(expected_unit_ids)},
                )
            ]

        failures = list(self.validate_coverage(normalized, expected_unit_ids, config))
        for failure in failures:
            if failure.request_id is None:
                failure.request_id = parsed_request.request_id
            if failure.group_id is None and parsed_request.group_id is not None:
                failure.group_id = parsed_request.group_id
        return normalized, failures

    def flatten_grouped_requests(
        self,
        parsed_requests: Sequence[ParsedRequestRecord],
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> tuple[list[AnnotationRecord], list[FailureRecord]]:
        annotations: list[AnnotationRecord] = []
        failures: list[FailureRecord] = []
        groups_by_id = {group.group_id: group for group in groups}

        for parsed_request in parsed_requests:
            if parsed_request.group_id is not None:
                group = groups_by_id.get(parsed_request.group_id)
                if group is None:
                    failures.append(
                        self.build_failure_record(
                            FailureKind.FLATTEN,
                            "parsed request references an unknown group_id during flattening",
                            request_id=parsed_request.request_id,
                            group_id=parsed_request.group_id,
                            details={"available_group_ids": sorted(groups_by_id)},
                        )
                    )
                    continue
                expected_unit_ids = list(group.unit_ids)
            elif parsed_request.unit_ids:
                expected_unit_ids = list(parsed_request.unit_ids)
            else:
                failures.append(
                    self.build_failure_record(
                        FailureKind.FLATTEN,
                        "parsed request is missing expected unit membership for flattening",
                        request_id=parsed_request.request_id,
                        group_id=parsed_request.group_id,
                    )
                )
                continue

            request_annotations, request_failures = self.flatten_request(parsed_request, expected_unit_ids, config)
            annotations.extend(request_annotations)
            failures.extend(request_failures)

        return annotations, failures
