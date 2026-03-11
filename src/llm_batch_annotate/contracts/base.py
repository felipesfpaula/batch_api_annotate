"""Framework interfaces for tasks, builders, parsers, providers, and stores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..configs.models import ArtifactStoreConfig, BaseProviderConfig, PromptAssetsConfig, RunConfig
from ..enums import ArtifactKind, FailureKind
from ..manifests.models import RunManifest
from .records import (
    AnnotationRecord,
    ArtifactRef,
    ExecutionHandle,
    FailureRecord,
    GroupRecord,
    ParsedRequestRecord,
    ProviderCapabilities,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
    UnitRecord,
)


class BaseTask(ABC):
    """Abstract task contract for unit planning, parsing, and validation."""

    @abstractmethod
    def validate_task_config(self, config: RunConfig) -> None:
        """Validate task-specific configuration before execution."""

    @abstractmethod
    def materialize_units(self, source_rows: Sequence[Mapping[str, Any]], config: RunConfig) -> Sequence[UnitRecord]:
        """Materialize atomic units from source rows."""

    @abstractmethod
    def plan_groups(self, units: Sequence[UnitRecord], config: RunConfig) -> Sequence[GroupRecord]:
        """Plan request groups from units."""

    @abstractmethod
    def build_requests(
        self,
        units: Sequence[UnitRecord],
        groups: Sequence[GroupRecord],
        builder: "BaseMessageBuilder",
        config: RunConfig,
    ) -> Sequence[RequestRecord]:
        """Coordinate request construction using the provided builder."""

    @abstractmethod
    def parse_request_outputs(
        self,
        raw_outputs: Sequence[RawOutputRecord],
        raw_errors: Sequence[RawErrorRecord],
        parser: "BaseParser",
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> tuple[Sequence[ParsedRequestRecord], Sequence[FailureRecord]]:
        """Coordinate parser-level extraction from raw provider artifacts."""

    @abstractmethod
    def flatten_annotations(
        self,
        parsed_requests: Sequence[ParsedRequestRecord],
        groups: Sequence[GroupRecord],
        parser: "BaseParser",
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        """Flatten request-level parsed payloads into per-unit annotations."""

    @abstractmethod
    def normalize_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        """Normalize final per-unit annotation rows."""

    @abstractmethod
    def validate_annotations(
        self,
        annotations: Sequence[AnnotationRecord],
        groups: Sequence[GroupRecord],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        """Validate final normalized annotations."""


class BaseMessageBuilder(ABC):
    """Abstract request-builder contract."""

    @abstractmethod
    def validate_inputs(
        self,
        units: Sequence[UnitRecord],
        prompt_assets: PromptAssetsConfig,
        config: RunConfig,
    ) -> None:
        """Validate required unit fields and prompt assets."""

    @abstractmethod
    def build_render_context(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        """Build a render context from units and optional group context."""

    @abstractmethod
    def build_system_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        """Build the system prompt content for a request."""

    @abstractmethod
    def build_user_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        """Build the user content for a request."""

    @abstractmethod
    def build_request_payload(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        """Build a provider-agnostic request payload description."""


class BaseParser(ABC):
    """Abstract parser contract for structured request results."""

    @abstractmethod
    def extract_payload(self, raw_output: RawOutputRecord, config: RunConfig) -> Mapping[str, Any]:
        """Extract the provider result payload from a raw output record."""

    @abstractmethod
    def deserialize_payload(self, payload: Mapping[str, Any], config: RunConfig) -> Mapping[str, Any]:
        """Deserialize structured content from a provider payload."""

    @abstractmethod
    def validate_top_level(self, parsed_payload: Mapping[str, Any], config: RunConfig) -> None:
        """Validate top-level response structure before flattening."""

    @abstractmethod
    def flatten_items(
        self,
        parsed_request: ParsedRequestRecord,
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        """Flatten a parsed request into per-unit annotation records."""

    @abstractmethod
    def validate_coverage(
        self,
        items: Sequence[AnnotationRecord],
        expected_unit_ids: Sequence[str],
        config: RunConfig,
    ) -> Sequence[FailureRecord]:
        """Validate coverage of flattened items against expected unit membership."""

    @abstractmethod
    def normalize_items(
        self,
        items: Sequence[AnnotationRecord],
        config: RunConfig,
    ) -> Sequence[AnnotationRecord]:
        """Normalize parsed item fields into the canonical annotation shape."""

    @abstractmethod
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
        """Emit a standardized parser failure record."""


class ExecutionProvider(ABC):
    """Abstract provider contract for batch submission and retrieval."""

    @abstractmethod
    def validate_provider_config(self, config: BaseProviderConfig) -> None:
        """Validate provider configuration prior to submission."""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Expose provider capability information."""

    @abstractmethod
    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        """Submit provider-ready request records and return execution handles."""

    @abstractmethod
    def poll_status(self, handle: ExecutionHandle, config: BaseProviderConfig) -> ExecutionHandle:
        """Poll the execution status for a provider job handle."""

    @abstractmethod
    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        """Retrieve raw outputs for a completed provider handle."""

    @abstractmethod
    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        """Retrieve raw errors for a provider handle."""


class ArtifactStore(ABC):
    """Abstract artifact store contract for canonical run outputs."""

    @abstractmethod
    def initialize_run(self, run_id: str, config: ArtifactStoreConfig) -> Path:
        """Initialize and return the canonical run namespace."""

    @abstractmethod
    def write_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        content: str | bytes,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        """Persist a named artifact and return its logical reference."""

    @abstractmethod
    def read_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> str | bytes:
        """Read a named artifact from the artifact store."""

    @abstractmethod
    def resolve_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        """Resolve a named artifact to its canonical logical reference."""

    @abstractmethod
    def write_manifest(self, manifest: RunManifest, config: ArtifactStoreConfig) -> ArtifactRef:
        """Persist the authoritative run manifest."""
