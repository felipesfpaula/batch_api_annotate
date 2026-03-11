from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from llm_batch_annotate import (
    AnnotationRecord,
    ArtifactKind,
    ArtifactRef,
    ArtifactStore,
    BaseMessageBuilder,
    BaseParser,
    BaseTask,
    ExecutionHandle,
    ExecutionProvider,
    FailureKind,
    FailureRecord,
    GroupRecord,
    ParsedRequestRecord,
    ProviderCapabilities,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
    UnitRecord,
)
from llm_batch_annotate.configs import ArtifactStoreConfig, BaseProviderConfig, PromptAssetsConfig, RunConfig


class FakeTask(BaseTask):
    def validate_task_config(self, config: RunConfig) -> None:
        return None

    def materialize_units(self, source_rows: Sequence[Mapping[str, Any]], config: RunConfig) -> Sequence[UnitRecord]:
        return [UnitRecord(unit_id="unit-1")]

    def plan_groups(self, units: Sequence[UnitRecord], config: RunConfig) -> Sequence[GroupRecord]:
        return [GroupRecord(group_id="group-1", unit_ids=["unit-1"])]

    def build_requests(
        self,
        units: Sequence[UnitRecord],
        groups: Sequence[GroupRecord],
        builder: BaseMessageBuilder,
        config: RunConfig,
    ) -> Sequence[RequestRecord]:
        return [RequestRecord(request_id="request-1", group_id="group-1", unit_ids=["unit-1"])]

    def parse_request_outputs(
        self,
        raw_outputs: Sequence[RawOutputRecord],
        raw_errors: Sequence[RawErrorRecord],
        parser: BaseParser,
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> tuple[Sequence[ParsedRequestRecord], Sequence[FailureRecord]]:
        return ([ParsedRequestRecord(request_id="request-1", group_id="group-1", unit_ids=["unit-1"])], [])

    def flatten_annotations(
        self,
        parsed_requests: Sequence[ParsedRequestRecord],
        groups: Sequence[GroupRecord],
        parser: BaseParser,
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        return [AnnotationRecord(unit_id="unit-1", request_id="request-1", group_id="group-1")]

    def normalize_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        return annotations

    def validate_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        return []


class FakeMessageBuilder(BaseMessageBuilder):
    def validate_inputs(
        self,
        units: Sequence[UnitRecord],
        prompt_assets: PromptAssetsConfig,
        config: RunConfig,
    ) -> None:
        return None

    def build_render_context(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        return {"unit_ids": [unit.unit_id for unit in units]}

    def build_system_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        return "system"

    def build_user_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        return "user"

    def build_request_payload(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        return {"messages": []}


class FakeParser(BaseParser):
    def extract_payload(self, raw_output: RawOutputRecord, config: RunConfig) -> Mapping[str, Any]:
        return raw_output.payload

    def deserialize_payload(self, payload: Mapping[str, Any], config: RunConfig) -> Mapping[str, Any]:
        return payload

    def validate_top_level(self, parsed_payload: Mapping[str, Any], config: RunConfig) -> None:
        return None

    def flatten_items(
        self,
        parsed_request: ParsedRequestRecord,
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        return [AnnotationRecord(unit_id=expected_unit_ids[0], request_id=parsed_request.request_id)]

    def validate_coverage(
        self,
        items: Sequence[AnnotationRecord],
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        return []

    def normalize_items(
        self,
        items: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        return items

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
            details=dict(details or {"source": "fake"}),
        )


class FakeExecutionProvider(ExecutionProvider):
    def validate_provider_config(self, config: BaseProviderConfig) -> None:
        return None

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind="custom")

    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        return [ExecutionHandle(provider_kind="custom", job_id="job-1")]

    def poll_status(self, handle: ExecutionHandle, config: BaseProviderConfig) -> ExecutionHandle:
        return handle

    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        return [RawOutputRecord(request_id="request-1")]

    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        return []


class FakeArtifactStore(ArtifactStore):
    def initialize_run(self, run_id: str, config: ArtifactStoreConfig) -> Path:
        return Path(config.root_dir) / run_id

    def write_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        content: str | bytes,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        return ArtifactRef(artifact_kind=artifact_kind, format="json", relative_path="metadata/manifest.json")

    def read_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> str | bytes:
        return "{}"

    def resolve_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        return ArtifactRef(artifact_kind=artifact_kind, format="json", relative_path="metadata/manifest.json")

    def write_manifest(self, manifest, config: ArtifactStoreConfig) -> ArtifactRef:
        return ArtifactRef(artifact_kind=ArtifactKind.MANIFEST, format="json", relative_path="metadata/manifest.json")


def test_base_contracts_are_abstract() -> None:
    with pytest.raises(TypeError):
        BaseTask()
    with pytest.raises(TypeError):
        BaseMessageBuilder()
    with pytest.raises(TypeError):
        BaseParser()
    with pytest.raises(TypeError):
        ExecutionProvider()
    with pytest.raises(TypeError):
        ArtifactStore()


def test_fake_implementations_satisfy_contracts() -> None:
    assert isinstance(FakeTask(), BaseTask)
    assert isinstance(FakeMessageBuilder(), BaseMessageBuilder)
    assert isinstance(FakeParser(), BaseParser)
    assert isinstance(FakeExecutionProvider(), ExecutionProvider)
    assert isinstance(FakeArtifactStore(), ArtifactStore)
