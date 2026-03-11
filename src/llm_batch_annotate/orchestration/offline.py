from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from pydantic import Field

from .._model import FrameworkModel
from ..configs.models import RunConfig
from ..contracts.base import BaseMessageBuilder, BaseParser
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
from ..tasks.base import ComposedTaskBase


class OfflineTaskPipelineResult(FrameworkModel):
    units: list[UnitRecord] = Field(default_factory=list)
    groups: list[GroupRecord] = Field(default_factory=list)
    requests: list[RequestRecord] = Field(default_factory=list)
    raw_outputs: list[RawOutputRecord] = Field(default_factory=list)
    raw_errors: list[RawErrorRecord] = Field(default_factory=list)
    parsed_requests: list[ParsedRequestRecord] = Field(default_factory=list)
    annotations: list[AnnotationRecord] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)


OfflineExecutor = Callable[
    [Sequence[RequestRecord]],
    tuple[Sequence[RawOutputRecord], Sequence[RawErrorRecord]],
]


class OfflineTaskPipeline:
    def __init__(
        self,
        *,
        task: ComposedTaskBase,
        builder: BaseMessageBuilder,
        parser: BaseParser,
        config: RunConfig,
    ) -> None:
        self.task = task
        self.builder = builder
        self.parser = parser
        self.config = config

    def prepare(self, source_rows: Sequence[Mapping[str, object]]) -> OfflineTaskPipelineResult:
        units = list(self.task.materialize_units(source_rows, self.config))
        groups = list(self.task.plan_groups(units, self.config))
        requests = list(self.task.build_requests(units, groups, self.builder, self.config))
        return OfflineTaskPipelineResult(
            units=units,
            groups=groups,
            requests=requests,
        )

    def _merge_request_metadata(
        self,
        requests: Sequence[RequestRecord],
        raw_outputs: Sequence[RawOutputRecord],
        raw_errors: Sequence[RawErrorRecord],
    ) -> tuple[list[RawOutputRecord], list[RawErrorRecord]]:
        request_lookup = {request.request_id: request for request in requests}

        merged_outputs: list[RawOutputRecord] = []
        for raw_output in raw_outputs:
            request = request_lookup.get(raw_output.request_id)
            metadata = dict(request.metadata) if request is not None else {}
            metadata.update(dict(raw_output.metadata))
            merged_outputs.append(
                RawOutputRecord(
                    request_id=raw_output.request_id,
                    status=raw_output.status,
                    payload=dict(raw_output.payload),
                    received_at=raw_output.received_at,
                    metadata=metadata,
                )
            )

        merged_errors: list[RawErrorRecord] = []
        for raw_error in raw_errors:
            request = request_lookup.get(raw_error.request_id)
            metadata = dict(request.metadata) if request is not None else {}
            metadata.update(dict(raw_error.metadata))
            merged_errors.append(
                RawErrorRecord(
                    request_id=raw_error.request_id,
                    status=raw_error.status,
                    error_type=raw_error.error_type,
                    message=raw_error.message,
                    payload=dict(raw_error.payload),
                    metadata=metadata,
                )
            )

        return merged_outputs, merged_errors

    def run(
        self,
        source_rows: Sequence[Mapping[str, object]],
        executor: OfflineExecutor,
    ) -> OfflineTaskPipelineResult:
        prepared = self.prepare(source_rows)
        raw_outputs, raw_errors = executor(prepared.requests)
        merged_outputs, merged_errors = self._merge_request_metadata(prepared.requests, raw_outputs, raw_errors)

        parsed_requests, parse_failures = self.task.parse_request_outputs(
            merged_outputs,
            merged_errors,
            self.parser,
            prepared.groups,
            self.config,
        )
        annotations, flatten_failures = self.task.flatten_annotations_with_failures(
            parsed_requests,
            prepared.groups,
            self.parser,
            self.config,
        )
        normalized_annotations = list(self.task.normalize_annotations(annotations, self.config))
        validation_failures = list(self.task.validate_annotations(normalized_annotations, prepared.groups, self.config))

        return OfflineTaskPipelineResult(
            units=prepared.units,
            groups=prepared.groups,
            requests=prepared.requests,
            raw_outputs=merged_outputs,
            raw_errors=merged_errors,
            parsed_requests=list(parsed_requests),
            annotations=normalized_annotations,
            failures=[*parse_failures, *flatten_failures, *validation_failures],
        )
