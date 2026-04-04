"""Run orchestration for prepare, submit, poll, retrieve, parse, and finalize."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import Field

from .._model import FrameworkModel
from ..configs.models import ArtifactStoreConfig, BaseProviderConfig, RunConfig
from ..contracts.base import ArtifactStore, BaseMessageBuilder, BaseParser, ExecutionProvider
from ..contracts.records import (
    AnnotationRecord,
    ArtifactRef,
    ExecutionHandle,
    FailureRecord,
    GroupRecord,
    ParsedRequestRecord,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
    UnitRecord,
)
from ..enums import ArtifactKind, ExecutionStatus, FailureKind, RunStatus, TaskKind
from ..execution import is_terminal_execution_status
from ..manifests.models import (
    ComponentIdentitySummary,
    GroupingSummary,
    InputSummary,
    ParseSummary,
    RunManifest,
    ValidationSummary,
    utc_now,
)
from ..tasks.base import ComposedTaskBase
from ..validation.coverage import validate_coverage

_ModelT = TypeVar("_ModelT", bound=FrameworkModel)


def default_run_id() -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


class TaskRunState(FrameworkModel):
    """In-memory view of a run and all artifacts accumulated so far."""

    manifest: RunManifest
    source_row_count: int = Field(default=0, ge=0)
    units: list[UnitRecord] = Field(default_factory=list)
    groups: list[GroupRecord] = Field(default_factory=list)
    requests: list[RequestRecord] = Field(default_factory=list)
    execution_handles: list[ExecutionHandle] = Field(default_factory=list)
    raw_outputs: list[RawOutputRecord] = Field(default_factory=list)
    raw_errors: list[RawErrorRecord] = Field(default_factory=list)
    effective_raw_outputs: list[RawOutputRecord] = Field(default_factory=list)
    effective_raw_errors: list[RawErrorRecord] = Field(default_factory=list)
    parsed_requests: list[ParsedRequestRecord] = Field(default_factory=list)
    annotations: list[AnnotationRecord] = Field(default_factory=list)
    provider_failures: list[FailureRecord] = Field(default_factory=list)
    parse_failures: list[FailureRecord] = Field(default_factory=list)
    flatten_failures: list[FailureRecord] = Field(default_factory=list)
    validation_failures: list[FailureRecord] = Field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    @property
    def failures(self) -> list[FailureRecord]:
        return [
            *self.provider_failures,
            *self.parse_failures,
            *self.flatten_failures,
            *self.validation_failures,
        ]


class TaskOrchestrator:
    """Coordinate end-to-end task execution against a configured provider."""

    def __init__(
        self,
        *,
        task: ComposedTaskBase,
        builder: BaseMessageBuilder,
        parser: BaseParser,
        provider: ExecutionProvider,
        artifact_store: ArtifactStore,
        config: RunConfig,
        run_id_factory: Callable[[], str] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.task = task
        self.builder = builder
        self.parser = parser
        self.provider = provider
        self.artifact_store = artifact_store
        self.config = config
        self.run_id_factory = run_id_factory or default_run_id
        self.sleep_fn = sleep_fn or time.sleep
        self.clock = clock

    def prepare(
        self,
        source_rows: Sequence[Mapping[str, object]],
        *,
        run_id: str | None = None,
    ) -> TaskRunState:
        resolved_run_id = run_id or self.run_id_factory()
        store_config = self.config.artifact_store.config
        self.artifact_store.initialize_run(resolved_run_id, store_config)

        units = list(self.task.materialize_units(source_rows, self.config))
        groups = list(self.task.plan_groups(units, self.config))
        requests = self._initialize_request_metadata(self.task.build_requests(units, groups, self.builder, self.config))

        manifest = RunManifest(
            run_id=resolved_run_id,
            run_name=self.config.run_metadata.run_name,
            task_kind=self.config.task_kind,
            status=RunStatus.RUNNING,
            started_at=self.clock(),
            components=self._component_summary(),
            input_summary=InputSummary(
                source_path=self.config.source_input.path,
                source_format=self.config.source_input.format,
                source_row_count=len(source_rows),
                unit_count=len(units),
                row_id_column=self.config.source_input.row_id_column,
            ),
            grouping_summary=self._grouping_summary(groups),
            artifacts=self._artifact_refs_for_run(resolved_run_id, store_config),
        )

        state = TaskRunState(
            manifest=manifest,
            source_row_count=len(source_rows),
            units=units,
            groups=groups,
            requests=requests,
        )

        self._write_json_artifact(state.run_id, ArtifactKind.RUN_CONFIG, self.config.model_dump(mode="json"), store_config)
        self._write_model_records(state.run_id, ArtifactKind.UNITS, units, store_config)
        self._write_model_records(state.run_id, ArtifactKind.GROUPS, groups, store_config)
        self._write_model_records(state.run_id, ArtifactKind.REQUESTS, requests, store_config)
        self._refresh_manifest_provider_metadata(state)
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        return state

    def submit(self, state: TaskRunState) -> TaskRunState:
        provider_config = self._provider_config()
        try:
            execution_handles = list(self.provider.submit_requests(state.requests, provider_config))
        except Exception as exc:
            state.provider_failures = [
                *state.provider_failures,
                self._failure_record(
                    FailureKind.PROVIDER_SUBMISSION,
                    str(exc),
                    details={"phase": "submit", "exception_type": type(exc).__name__},
                ),
            ]
            self._refresh_manifest_provider_metadata(state)
            self._touch_manifest(state.manifest)
            self._persist_manifest(state)
            return state

        state.execution_handles = execution_handles
        state.manifest.execution_handles = list(execution_handles)
        self._refresh_manifest_provider_metadata(state)
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        return state

    def poll(
        self,
        state: TaskRunState,
        *,
        until_terminal: bool = True,
        poll_interval_seconds: float = 0.0,
        max_polls: int | None = None,
        on_poll: Callable[[TaskRunState, int, int | None], None] | None = None,
    ) -> TaskRunState:
        if not state.execution_handles:
            return state

        poll_count = 0
        while True:
            polled_handles: list[ExecutionHandle] = []
            for handle in state.execution_handles:
                try:
                    polled_handles.append(self.provider.poll_status(handle, self._provider_config()))
                except Exception as exc:
                    state.provider_failures = [
                        *state.provider_failures,
                        self._failure_record(
                            FailureKind.PROVIDER_EXECUTION,
                            str(exc),
                            details={
                                "phase": "poll",
                                "exception_type": type(exc).__name__,
                                "job_id": handle.job_id,
                            },
                        ),
                    ]
                    polled_handles.append(handle)

            state.execution_handles = polled_handles
            state.manifest.execution_handles = list(polled_handles)
            self._refresh_manifest_provider_metadata(state)
            self._touch_manifest(state.manifest)
            self._persist_manifest(state)

            poll_count += 1
            if on_poll is not None:
                on_poll(state, poll_count, max_polls)
            all_terminal = all(is_terminal_execution_status(handle.status) for handle in polled_handles)
            if not until_terminal or all_terminal:
                return state
            if max_polls is not None and poll_count >= max_polls:
                return state
            if poll_interval_seconds > 0:
                self.sleep_fn(poll_interval_seconds)

    def retrieve(self, state: TaskRunState) -> TaskRunState:
        raw_outputs: list[RawOutputRecord] = []
        raw_errors: list[RawErrorRecord] = []

        for handle in state.execution_handles:
            try:
                raw_outputs.extend(self.provider.retrieve_outputs(handle, self._provider_config()))
                raw_errors.extend(self.provider.retrieve_errors(handle, self._provider_config()))
            except Exception as exc:
                state.provider_failures = [
                    *state.provider_failures,
                    self._failure_record(
                        FailureKind.RETRIEVAL,
                        str(exc),
                        details={
                            "phase": "retrieve",
                            "exception_type": type(exc).__name__,
                            "job_id": handle.job_id,
                        },
                    ),
                ]

        deduped_outputs = self._dedupe_raw_outputs([*state.raw_outputs, *raw_outputs])
        deduped_errors = self._dedupe_raw_errors([*state.raw_errors, *raw_errors])
        merged_outputs, merged_errors = self._merge_request_metadata(state.requests, deduped_outputs, deduped_errors)
        state.raw_outputs = merged_outputs
        state.raw_errors = merged_errors
        state.effective_raw_outputs, state.effective_raw_errors = self._effective_raw_results(state)

        store_config = self.config.artifact_store.config
        self._write_model_records(state.run_id, ArtifactKind.RAW_OUTPUTS, merged_outputs, store_config)
        self._write_model_records(state.run_id, ArtifactKind.RAW_ERRORS, merged_errors, store_config)
        self._refresh_manifest_provider_metadata(state)
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        return state

    def parse(self, state: TaskRunState) -> TaskRunState:
        if not state.effective_raw_outputs and not state.effective_raw_errors:
            state.effective_raw_outputs, state.effective_raw_errors = self._effective_raw_results(state)

        parsed_requests, parse_failures = self._parse_effective_results(state)
        parsed_requests, parse_failures = self._retry_failed_requests(
            state,
            parsed_requests,
            parse_failures,
        )
        state.parsed_requests = list(parsed_requests)
        state.parse_failures = list(parse_failures)

        self._rewrite_attempt_artifacts(state)
        self._write_model_records(
            state.run_id,
            ArtifactKind.PARSED_REQUESTS,
            state.parsed_requests,
            self.config.artifact_store.config,
        )
        state.manifest.parse_summary = ParseSummary(
            request_count=len(state.requests),
            parsed_request_count=len(state.parsed_requests),
            failure_count=len(state.parse_failures),
        )
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        return state

    def flatten(self, state: TaskRunState) -> TaskRunState:
        annotations, flatten_failures, validation_failures = self._flatten_current_annotations(state)
        annotations, flatten_failures, validation_failures = self._repair_failed_items(
            state,
            annotations,
            flatten_failures,
            validation_failures,
        )

        state.annotations = list(annotations)
        state.flatten_failures = list(flatten_failures)
        state.validation_failures = list(validation_failures)

        store_config = self.config.artifact_store.config
        self._rewrite_attempt_artifacts(state)
        self._write_json_records(
            state.run_id,
            ArtifactKind.RESPONSES,
            [self._response_row_from_annotation(annotation) for annotation in state.annotations],
            store_config,
        )
        self._write_model_records(state.run_id, ArtifactKind.FAILURES, state.failures, store_config)
        state.manifest.parse_summary = ParseSummary(
            request_count=len(state.requests),
            parsed_request_count=len(state.parsed_requests),
            failure_count=len(state.parse_failures),
        )
        state.manifest.validation_summary = self._validation_summary(state)
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        return state

    def finalize(self, state: TaskRunState) -> TaskRunState:
        state.manifest.parse_summary = ParseSummary(
            request_count=len(state.requests),
            parsed_request_count=len(state.parsed_requests),
            failure_count=len(state.parse_failures),
        )
        state.manifest.validation_summary = self._validation_summary(state)
        state.manifest.status = self._final_status(state)
        state.manifest.execution_handles = list(state.execution_handles)
        state.manifest.completed_at = self.clock()
        self._refresh_manifest_provider_metadata(state)
        self._touch_manifest(state.manifest)
        self._persist_manifest(state)
        self._persist_summary(state)
        return state

    def has_run(self, run_id: str) -> bool:
        try:
            self._read_json_model_artifact(run_id, ArtifactKind.MANIFEST, RunManifest, required=True)
        except FileNotFoundError:
            return False
        return True

    def load_state(self, run_id: str) -> TaskRunState:
        manifest = self._read_json_model_artifact(run_id, ArtifactKind.MANIFEST, RunManifest, required=True)
        units = self._read_jsonl_model_artifact(run_id, ArtifactKind.UNITS, UnitRecord)
        groups = self._read_jsonl_model_artifact(run_id, ArtifactKind.GROUPS, GroupRecord)
        requests = self._read_jsonl_model_artifact(run_id, ArtifactKind.REQUESTS, RequestRecord)
        raw_outputs = self._read_jsonl_model_artifact(run_id, ArtifactKind.RAW_OUTPUTS, RawOutputRecord)
        raw_errors = self._read_jsonl_model_artifact(run_id, ArtifactKind.RAW_ERRORS, RawErrorRecord)
        parsed_requests = self._read_jsonl_model_artifact(run_id, ArtifactKind.PARSED_REQUESTS, ParsedRequestRecord)
        annotations = [
            self._annotation_from_response_row(response_row)
            for response_row in self._read_jsonl_artifact(run_id, ArtifactKind.RESPONSES)
        ]
        failures = self._read_jsonl_model_artifact(run_id, ArtifactKind.FAILURES, FailureRecord)
        provider_failures, parse_failures, flatten_failures, validation_failures = self._split_failures(failures)

        state = TaskRunState(
            manifest=manifest,
            source_row_count=manifest.input_summary.source_row_count or len(units),
            units=units,
            groups=groups,
            requests=requests,
            execution_handles=list(manifest.execution_handles),
            raw_outputs=raw_outputs,
            raw_errors=raw_errors,
            parsed_requests=parsed_requests,
            annotations=annotations,
            provider_failures=provider_failures,
            parse_failures=parse_failures,
            flatten_failures=flatten_failures,
            validation_failures=validation_failures,
        )
        state.effective_raw_outputs, state.effective_raw_errors = self._effective_raw_results(state)
        return state

    def resume(
        self,
        run_id: str,
        *,
        poll_until_terminal: bool = True,
        poll_interval_seconds: float = 0.0,
        max_polls: int | None = None,
        on_poll: Callable[[TaskRunState, int, int | None], None] | None = None,
    ) -> TaskRunState:
        state = self.load_state(run_id)
        if not state.execution_handles:
            self.finalize(state)
            return state

        if not all(is_terminal_execution_status(handle.status) for handle in state.execution_handles):
            self.poll(
                state,
                until_terminal=poll_until_terminal,
                poll_interval_seconds=poll_interval_seconds,
                max_polls=max_polls,
                on_poll=on_poll,
            )

        if state.execution_handles and not all(is_terminal_execution_status(handle.status) for handle in state.execution_handles):
            self.finalize(state)
            return state

        self.retrieve(state)
        self.parse(state)
        self.flatten(state)
        self.finalize(state)
        return state

    def run(
        self,
        source_rows: Sequence[Mapping[str, object]],
        *,
        run_id: str | None = None,
        poll_until_terminal: bool = True,
        poll_interval_seconds: float = 0.0,
        max_polls: int | None = None,
    ) -> TaskRunState:
        state = self.prepare(source_rows, run_id=run_id)
        self.submit(state)
        self.poll(
            state,
            until_terminal=poll_until_terminal,
            poll_interval_seconds=poll_interval_seconds,
            max_polls=max_polls,
        )
        if state.execution_handles and not all(is_terminal_execution_status(handle.status) for handle in state.execution_handles):
            self.finalize(state)
            return state
        self.retrieve(state)
        self.parse(state)
        self.flatten(state)
        self.finalize(state)
        return state

    def _component_summary(self) -> ComponentIdentitySummary:
        return ComponentIdentitySummary(
            task=self.config.task,
            builder=self.config.builder,
            parser=self.config.parser,
            provider=self.config.provider.component,
            artifact_store=self.config.artifact_store.component,
        )

    def _grouping_summary(self, groups: Sequence[GroupRecord]) -> GroupingSummary | None:
        if self.config.grouping is None:
            return None
        return GroupingSummary(
            strategy=self.config.grouping.strategy,
            requested_group_size=self.config.grouping.group_size,
            group_count=len(groups),
            exact_coverage=self.config.grouping.exact_coverage,
        )

    def _artifact_refs_for_run(
        self,
        run_id: str,
        config: ArtifactStoreConfig,
    ) -> dict[ArtifactKind, ArtifactRef]:
        return {
            artifact_kind: self.artifact_store.resolve_artifact(run_id, artifact_kind, config)
            for artifact_kind in ArtifactKind
        }

    def _provider_config(self) -> BaseProviderConfig:
        return self.config.provider.config

    def _touch_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = self.clock()

    def _refresh_manifest_provider_metadata(self, state: TaskRunState) -> None:
        capabilities = self.provider.get_capabilities().model_dump(mode="json")
        state.manifest.provider_metadata = {
            "provider_kind": self.config.provider.config.provider_kind.value,
            "capabilities": capabilities,
            "handle_count": len(state.execution_handles),
            "handles": [handle.model_dump(mode="json") for handle in state.execution_handles],
            "raw_output_count": len(state.raw_outputs),
            "raw_error_count": len(state.raw_errors),
            "effective_raw_output_count": len(state.effective_raw_outputs),
            "effective_raw_error_count": len(state.effective_raw_errors),
        }
        state.manifest.execution_handles = list(state.execution_handles)

    def _initialize_request_metadata(self, requests: Sequence[RequestRecord]) -> list[RequestRecord]:
        initialized_requests: list[RequestRecord] = []
        for request in requests:
            metadata = {
                **dict(request.metadata),
                "logical_request_id": request.request_id,
                "retry_attempt": 1,
                "retry_scope": "original",
            }
            initialized_requests.append(request.model_copy(update={"metadata": metadata}))
        return initialized_requests

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
            merged_metadata = dict(request.metadata) if request is not None else {}
            merged_metadata.update(dict(raw_output.metadata))
            merged_outputs.append(raw_output.model_copy(update={"metadata": merged_metadata}))

        merged_errors: list[RawErrorRecord] = []
        for raw_error in raw_errors:
            request = request_lookup.get(raw_error.request_id)
            merged_metadata = dict(request.metadata) if request is not None else {}
            merged_metadata.update(dict(raw_error.metadata))
            merged_errors.append(raw_error.model_copy(update={"metadata": merged_metadata}))

        return merged_outputs, merged_errors

    def _dedupe_raw_outputs(self, raw_outputs: Sequence[RawOutputRecord]) -> list[RawOutputRecord]:
        latest_by_key: dict[tuple[str, str | None, str | None], RawOutputRecord] = {}
        order: list[tuple[str, str | None, str | None]] = []
        for raw_output in raw_outputs:
            key = (raw_output.request_id, raw_output.job_id, raw_output.result_id)
            if key not in latest_by_key:
                order.append(key)
            latest_by_key[key] = raw_output
        return [latest_by_key[key] for key in order]

    def _dedupe_raw_errors(self, raw_errors: Sequence[RawErrorRecord]) -> list[RawErrorRecord]:
        latest_by_key: dict[tuple[str, str | None, str | None, str | None], RawErrorRecord] = {}
        order: list[tuple[str, str | None, str | None, str | None]] = []
        for raw_error in raw_errors:
            key = (raw_error.request_id, raw_error.job_id, raw_error.result_id, raw_error.error_type)
            if key not in latest_by_key:
                order.append(key)
            latest_by_key[key] = raw_error
        return [latest_by_key[key] for key in order]

    def _read_artifact_text(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        *,
        required: bool = False,
    ) -> str:
        try:
            content = self.artifact_store.read_artifact(run_id, artifact_kind, self.config.artifact_store.config)
        except FileNotFoundError:
            if required:
                raise
            return ""
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content

    def _read_json_model_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        model_type: type[_ModelT],
        *,
        required: bool = False,
    ) -> _ModelT:
        content = self._read_artifact_text(run_id, artifact_kind, required=required)
        if not content.strip():
            msg = f"artifact {artifact_kind.value!r} is empty for run {run_id!r}"
            raise ValueError(msg)
        return model_type.model_validate_json(content)

    def _read_jsonl_model_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        model_type: type[_ModelT],
    ) -> list[_ModelT]:
        content = self._read_artifact_text(run_id, artifact_kind, required=False)
        records: list[_ModelT] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            records.append(model_type.model_validate_json(line))
        return records

    def _read_jsonl_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
    ) -> list[dict[str, Any]]:
        content = self._read_artifact_text(run_id, artifact_kind, required=False)
        records: list[dict[str, Any]] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                msg = f"artifact {artifact_kind.value!r} must contain JSON objects on each line"
                raise ValueError(msg)
            records.append(dict(payload))
        return records

    def _split_failures(
        self,
        failures: Sequence[FailureRecord],
    ) -> tuple[list[FailureRecord], list[FailureRecord], list[FailureRecord], list[FailureRecord]]:
        provider_failure_kinds = {
            FailureKind.REQUEST_CONSTRUCTION,
            FailureKind.PROVIDER_SUBMISSION,
            FailureKind.PROVIDER_EXECUTION,
            FailureKind.RETRIEVAL,
        }
        provider_failures: list[FailureRecord] = []
        parse_failures: list[FailureRecord] = []
        flatten_failures: list[FailureRecord] = []
        validation_failures: list[FailureRecord] = []
        for failure in failures:
            if failure.failure_kind in provider_failure_kinds:
                provider_failures.append(failure)
            elif failure.failure_kind is FailureKind.PARSE:
                parse_failures.append(failure)
            elif failure.failure_kind is FailureKind.FLATTEN:
                flatten_failures.append(failure)
            elif failure.failure_kind is FailureKind.VALIDATION:
                validation_failures.append(failure)
        return provider_failures, parse_failures, flatten_failures, validation_failures

    def _effective_raw_results(self, state: TaskRunState) -> tuple[list[RawOutputRecord], list[RawErrorRecord]]:
        latest_outputs: dict[str, list[RawOutputRecord]] = {}
        latest_errors: dict[str, list[RawErrorRecord]] = {}
        latest_attempts: dict[str, int] = {}

        for raw_output in state.raw_outputs:
            logical_request_id = self._logical_request_id_from_metadata(raw_output.metadata, raw_output.request_id)
            retry_attempt = self._retry_attempt_from_metadata(raw_output.metadata)
            current_attempt = latest_attempts.get(logical_request_id, 0)
            if retry_attempt < current_attempt:
                continue
            if retry_attempt > current_attempt:
                latest_outputs[logical_request_id] = []
                latest_errors[logical_request_id] = []
                latest_attempts[logical_request_id] = retry_attempt
            latest_outputs.setdefault(logical_request_id, []).append(raw_output)

        for raw_error in state.raw_errors:
            logical_request_id = self._logical_request_id_from_metadata(raw_error.metadata, raw_error.request_id)
            retry_attempt = self._retry_attempt_from_metadata(raw_error.metadata)
            current_attempt = latest_attempts.get(logical_request_id, 0)
            if retry_attempt < current_attempt:
                continue
            if retry_attempt > current_attempt:
                latest_outputs[logical_request_id] = []
                latest_errors[logical_request_id] = []
                latest_attempts[logical_request_id] = retry_attempt
            if not latest_outputs.get(logical_request_id):
                latest_errors.setdefault(logical_request_id, []).append(raw_error)

        effective_outputs: list[RawOutputRecord] = []
        effective_errors: list[RawErrorRecord] = []
        for logical_request_id in latest_attempts:
            outputs = latest_outputs.get(logical_request_id, [])
            errors = latest_errors.get(logical_request_id, [])
            if outputs:
                effective_outputs.extend(outputs)
            elif errors:
                effective_errors.extend(errors)
        return effective_outputs, effective_errors

    def _parse_effective_results(
        self,
        state: TaskRunState,
    ) -> tuple[list[ParsedRequestRecord], list[FailureRecord]]:
        parsed_requests, parse_failures = self.task.parse_request_outputs(
            state.effective_raw_outputs,
            state.effective_raw_errors,
            self.parser,
            state.groups,
            self.config,
        )
        return list(parsed_requests), list(parse_failures)

    def _retry_failed_requests(
        self,
        state: TaskRunState,
        parsed_requests: list[ParsedRequestRecord],
        parse_failures: list[FailureRecord],
    ) -> tuple[list[ParsedRequestRecord], list[FailureRecord]]:
        retry_policy = self.config.retry_policy
        if not retry_policy.enabled or not retry_policy.retry_failed_requests or retry_policy.max_attempts <= 1:
            return parsed_requests, parse_failures

        while True:
            retry_targets = self._retryable_request_ids(state, parse_failures)
            if not retry_targets:
                return parsed_requests, parse_failures

            retry_requests = self._build_request_retries(state, retry_targets)
            if not retry_requests:
                return parsed_requests, parse_failures

            state.requests.extend(retry_requests)
            retry_outputs, retry_errors = self._execute_requests(retry_requests)
            state.raw_outputs.extend(retry_outputs)
            state.raw_errors.extend(retry_errors)
            state.effective_raw_outputs, state.effective_raw_errors = self._effective_raw_results(state)
            parsed_requests, parse_failures = self._parse_effective_results(state)

    def _retryable_request_ids(
        self,
        state: TaskRunState,
        parse_failures: Sequence[FailureRecord],
    ) -> list[str]:
        latest_requests = self._latest_request_attempts(state.requests)
        retry_targets: set[str] = set()

        for raw_error in state.effective_raw_errors:
            logical_request_id = self._logical_request_id_from_metadata(raw_error.metadata, raw_error.request_id)
            if self._request_can_retry(logical_request_id, latest_requests):
                retry_targets.add(logical_request_id)

        for failure in parse_failures:
            if failure.request_id is None:
                continue
            request = latest_requests.get(self._logical_request_id_from_request_id(state.requests, failure.request_id))
            if request is None:
                continue
            logical_request_id = self._logical_request_id(request)
            if self._request_can_retry(logical_request_id, latest_requests):
                retry_targets.add(logical_request_id)

        return sorted(retry_targets)

    def _build_request_retries(
        self,
        state: TaskRunState,
        logical_request_ids: Sequence[str],
    ) -> list[RequestRecord]:
        latest_requests = self._latest_request_attempts(state.requests)
        retry_requests: list[RequestRecord] = []
        for logical_request_id in logical_request_ids:
            latest_request = latest_requests.get(logical_request_id)
            if latest_request is None:
                continue
            next_attempt = self._retry_attempt(latest_request) + 1
            retry_requests.append(
                RequestRecord(
                    request_id=f"{logical_request_id}-retry-{next_attempt:02d}",
                    group_id=latest_request.group_id,
                    unit_ids=list(latest_request.unit_ids),
                    payload=dict(latest_request.payload),
                    metadata={
                        **dict(latest_request.metadata),
                        "logical_request_id": logical_request_id,
                        "retry_attempt": next_attempt,
                        "retry_scope": "request",
                        "retry_of_request_id": latest_request.request_id,
                    },
                )
            )
        return retry_requests

    def _repair_failed_items(
        self,
        state: TaskRunState,
        annotations: list[AnnotationRecord],
        flatten_failures: list[FailureRecord],
        validation_failures: list[FailureRecord],
    ) -> tuple[list[AnnotationRecord], list[FailureRecord], list[FailureRecord]]:
        retry_policy = self.config.retry_policy
        current_annotations = list(annotations)
        current_flatten_failures = list(flatten_failures)
        current_validation_failures = list(validation_failures)
        if not retry_policy.enabled or not retry_policy.retry_failed_items or retry_policy.max_attempts <= 1:
            return current_annotations, current_flatten_failures, current_validation_failures

        for repair_attempt in range(2, retry_policy.max_attempts + 1):
            missing_unit_ids = self._missing_unit_ids(state, current_annotations)
            if not missing_unit_ids:
                break

            repair_requests = self._build_item_repair_requests(state, missing_unit_ids, repair_attempt)
            if not repair_requests:
                break

            state.requests.extend(repair_requests)
            repair_outputs, repair_errors = self._execute_requests(repair_requests)
            state.raw_outputs.extend(repair_outputs)
            state.raw_errors.extend(repair_errors)
            state.effective_raw_outputs, state.effective_raw_errors = self._effective_raw_results(state)
            parsed_requests, parse_failures = self._parse_effective_results(state)
            state.parsed_requests = parsed_requests
            state.parse_failures = parse_failures
            current_annotations, current_flatten_failures, current_validation_failures = self._flatten_current_annotations(
                state
            )

        return current_annotations, current_flatten_failures, current_validation_failures

    def _build_item_repair_requests(
        self,
        state: TaskRunState,
        unit_ids: Sequence[str],
        repair_attempt: int,
    ) -> list[RequestRecord]:
        units_by_id = {unit.unit_id: unit for unit in state.units}
        repair_requests: list[RequestRecord] = []
        for unit_id in unit_ids:
            unit = units_by_id.get(unit_id)
            if unit is None:
                continue
            payload = dict(self.builder.build_request_payload([unit], None, self.config))
            repair_request_id = f"repair-item-{unit_id}-attempt-{repair_attempt:02d}"
            repair_requests.append(
                RequestRecord(
                    request_id=repair_request_id,
                    group_id=None,
                    unit_ids=[unit_id],
                    payload=payload,
                    metadata={
                        "logical_request_id": repair_request_id,
                        "retry_attempt": repair_attempt,
                        "retry_scope": "item",
                        "repair_unit_id": unit_id,
                        "unit_ids": [unit_id],
                    },
                )
            )
        return repair_requests

    def _execute_requests(
        self,
        requests: Sequence[RequestRecord],
    ) -> tuple[list[RawOutputRecord], list[RawErrorRecord]]:
        if not requests:
            return [], []

        retry_handles = list(self.provider.submit_requests(requests, self._provider_config()))
        polled_handles = [
            self._poll_handle_to_terminal(handle)
            for handle in retry_handles
        ]
        stateful_outputs: list[RawOutputRecord] = []
        stateful_errors: list[RawErrorRecord] = []
        for handle in polled_handles:
            stateful_outputs.extend(self.provider.retrieve_outputs(handle, self._provider_config()))
            stateful_errors.extend(self.provider.retrieve_errors(handle, self._provider_config()))

        merged_outputs, merged_errors = self._merge_request_metadata(requests, stateful_outputs, stateful_errors)
        return merged_outputs, merged_errors

    def _poll_handle_to_terminal(self, handle: ExecutionHandle) -> ExecutionHandle:
        current_handle = handle
        retry_policy = self.config.retry_policy
        max_attempts = max(1, retry_policy.max_attempts)
        poll_count = 0
        while True:
            current_handle = self.provider.poll_status(current_handle, self._provider_config())
            poll_count += 1
            if is_terminal_execution_status(current_handle.status) or poll_count >= max_attempts:
                return current_handle

    def _flatten_current_annotations(
        self,
        state: TaskRunState,
    ) -> tuple[list[AnnotationRecord], list[FailureRecord], list[FailureRecord]]:
        annotations, flatten_failures = self.task.flatten_annotations_with_failures(
            state.parsed_requests,
            state.groups,
            self.parser,
            self.config,
        )
        normalized_annotations = list(self.task.normalize_annotations(annotations, self.config))
        validation_failures = list(self.task.validate_annotations(normalized_annotations, state.groups, self.config))
        return normalized_annotations, list(flatten_failures), list(validation_failures)

    def _rewrite_attempt_artifacts(self, state: TaskRunState) -> None:
        store_config = self.config.artifact_store.config
        self._write_model_records(state.run_id, ArtifactKind.REQUESTS, state.requests, store_config)
        self._write_model_records(state.run_id, ArtifactKind.RAW_OUTPUTS, state.raw_outputs, store_config)
        self._write_model_records(state.run_id, ArtifactKind.RAW_ERRORS, state.raw_errors, store_config)
        self._refresh_manifest_provider_metadata(state)

    def _latest_request_attempts(self, requests: Sequence[RequestRecord]) -> dict[str, RequestRecord]:
        latest_requests: dict[str, RequestRecord] = {}
        for request in requests:
            logical_request_id = self._logical_request_id(request)
            current = latest_requests.get(logical_request_id)
            if current is None or self._retry_attempt(request) >= self._retry_attempt(current):
                latest_requests[logical_request_id] = request
        return latest_requests

    def _logical_request_id(self, request: RequestRecord) -> str:
        return self._logical_request_id_from_metadata(request.metadata, request.request_id)

    def _logical_request_id_from_request_id(
        self,
        requests: Sequence[RequestRecord],
        request_id: str,
    ) -> str:
        request_lookup = {request.request_id: request for request in requests}
        request = request_lookup.get(request_id)
        if request is None:
            return request_id
        return self._logical_request_id(request)

    def _logical_request_id_from_metadata(self, metadata: Mapping[str, Any], fallback: str) -> str:
        value = metadata.get("logical_request_id", fallback)
        return str(value)

    def _retry_attempt(self, request: RequestRecord) -> int:
        return self._retry_attempt_from_metadata(request.metadata)

    def _retry_attempt_from_metadata(self, metadata: Mapping[str, Any]) -> int:
        value = metadata.get("retry_attempt", 1)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1

    def _request_can_retry(
        self,
        logical_request_id: str,
        latest_requests: Mapping[str, RequestRecord],
    ) -> bool:
        latest_request = latest_requests.get(logical_request_id)
        if latest_request is None:
            return False
        return self._retry_attempt(latest_request) < self.config.retry_policy.max_attempts

    def _missing_unit_ids(
        self,
        state: TaskRunState,
        annotations: Sequence[AnnotationRecord],
    ) -> list[str]:
        expected_unit_ids = [unit_id for group in state.groups for unit_id in group.unit_ids]
        exact_coverage = True if self.config.grouping is None else self.config.grouping.exact_coverage
        result = validate_coverage(expected_unit_ids, annotations, exact_coverage=exact_coverage)
        return list(result.missing_unit_ids)

    def _validation_summary(self, state: TaskRunState) -> ValidationSummary:
        expected_unit_ids = [unit_id for group in state.groups for unit_id in group.unit_ids]
        exact_coverage = True if self.config.grouping is None else self.config.grouping.exact_coverage
        if state.execution_handles and not all(is_terminal_execution_status(handle.status) for handle in state.execution_handles):
            return ValidationSummary(
                valid=not state.provider_failures and not state.parse_failures and not state.flatten_failures,
                exact_coverage=exact_coverage,
            )
        result = validate_coverage(expected_unit_ids, state.annotations, exact_coverage=exact_coverage)
        return ValidationSummary(
            valid=result.valid and not state.provider_failures and not state.parse_failures and not state.flatten_failures,
            exact_coverage=exact_coverage,
            missing_unit_count=len(result.missing_unit_ids),
            unexpected_unit_count=len(result.unexpected_unit_ids),
            duplicate_unit_count=len(result.duplicate_unit_ids),
        )

    def _final_status(self, state: TaskRunState) -> RunStatus:
        has_failures = bool(state.failures)

        if has_failures:
            return RunStatus.PARTIAL if state.annotations else RunStatus.FAILED
        if state.execution_handles and not all(is_terminal_execution_status(handle.status) for handle in state.execution_handles):
            return RunStatus.RUNNING
        if state.requests or state.execution_handles:
            return RunStatus.SUCCEEDED
        return RunStatus.PENDING

    def _persist_manifest(self, state: TaskRunState) -> None:
        if self.config.output.write_manifest:
            self.artifact_store.write_manifest(state.manifest, self.config.artifact_store.config)

    def _persist_summary(self, state: TaskRunState) -> None:
        if not self.config.output.write_summary:
            return
        summary = {
            "run_id": state.manifest.run_id,
            "run_name": state.manifest.run_name,
            "status": state.manifest.status.value,
            "counts": {
                "source_rows": state.source_row_count,
                "units": len(state.units),
                "groups": len(state.groups),
                "requests": len(state.requests),
                "execution_handles": len(state.execution_handles),
                "raw_outputs": len(state.raw_outputs),
                "raw_errors": len(state.raw_errors),
                "parsed_requests": len(state.parsed_requests),
                "annotations": len(state.annotations),
                "failures": len(state.failures),
            },
            "artifacts": {
                artifact_kind.value: artifact_ref.model_dump(mode="json")
                for artifact_kind, artifact_ref in state.manifest.artifacts.items()
            },
            "provider_metadata": dict(state.manifest.provider_metadata),
            "parse_summary": state.manifest.parse_summary.model_dump(mode="json"),
            "validation_summary": state.manifest.validation_summary.model_dump(mode="json"),
            "timestamps": {
                "created_at": state.manifest.created_at.isoformat(),
                "updated_at": state.manifest.updated_at.isoformat(),
                "started_at": state.manifest.started_at.isoformat() if state.manifest.started_at is not None else None,
                "completed_at": (
                    state.manifest.completed_at.isoformat() if state.manifest.completed_at is not None else None
                ),
            },
        }
        self._write_json_artifact(state.run_id, ArtifactKind.SUMMARY, summary, self.config.artifact_store.config)

    def _write_json_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        payload: Any,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        content = json.dumps(payload, indent=2, sort_keys=True)
        return self.artifact_store.write_artifact(run_id, artifact_kind, content + "\n", config)

    def _write_model_records(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        records: Sequence[FrameworkModel],
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        content = "".join(record.model_dump_json() + "\n" for record in records)
        return self.artifact_store.write_artifact(run_id, artifact_kind, content, config)

    def _write_json_records(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        records: Sequence[Mapping[str, Any]],
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        content = "".join(json.dumps(dict(record), sort_keys=True) + "\n" for record in records)
        return self.artifact_store.write_artifact(run_id, artifact_kind, content, config)

    def _response_row_from_annotation(self, annotation: AnnotationRecord) -> dict[str, Any]:
        row_id_column = self.config.source_input.row_id_column
        response_row = {
            row_id_column: annotation.unit_id,
            "request_id": annotation.request_id,
            "fields": dict(annotation.fields),
            "metadata": dict(annotation.metadata),
        }
        if self.config.task_kind is TaskKind.GROUPED and annotation.group_id is not None:
            response_row["group_id"] = annotation.group_id
        return response_row

    def _annotation_from_response_row(self, response_row: Mapping[str, Any]) -> AnnotationRecord:
        row_id_column = self.config.source_input.row_id_column
        if row_id_column not in response_row:
            msg = f"response row is missing the configured row id field {row_id_column!r}"
            raise ValueError(msg)

        request_id = response_row.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            msg = "response row is missing a non-empty 'request_id'"
            raise ValueError(msg)

        fields = response_row.get("fields", {})
        if not isinstance(fields, Mapping):
            msg = "response row 'fields' must be a mapping"
            raise ValueError(msg)

        metadata = response_row.get("metadata", {})
        if not isinstance(metadata, Mapping):
            msg = "response row 'metadata' must be a mapping"
            raise ValueError(msg)

        group_id = response_row.get("group_id")
        if group_id is not None:
            group_id = str(group_id)

        return AnnotationRecord(
            unit_id=str(response_row[row_id_column]),
            request_id=request_id,
            group_id=group_id,
            fields=dict(fields),
            metadata=dict(metadata),
        )

    def _failure_record(
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
            details=dict(details or {"orchestrator": self.__class__.__name__}),
        )


__all__ = [
    "TaskOrchestrator",
    "TaskRunState",
    "default_run_id",
]
