"""Manifest and summary models persisted for each run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import Field, model_validator

from .._model import FrameworkModel
from ..contracts.records import ArtifactRef, ComponentRef, ExecutionHandle
from ..enums import ArtifactKind, GroupingStrategy, RunStatus, SourceFormat, TaskKind


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ComponentIdentitySummary(FrameworkModel):
    """Serializable identity references for the components used in a run."""

    task: ComponentRef
    builder: ComponentRef
    parser: ComponentRef
    provider: ComponentRef
    artifact_store: ComponentRef


class InputSummary(FrameworkModel):
    """Summary of the source input loaded for a run."""

    source_path: str = Field(min_length=1)
    source_format: SourceFormat
    source_row_count: int | None = Field(default=None, ge=0)
    unit_count: int | None = Field(default=None, ge=0)
    row_id_column: str = Field(min_length=1)


class GroupingSummary(FrameworkModel):
    """Summary of the grouping plan applied to the run."""

    strategy: GroupingStrategy | None = None
    requested_group_size: int | None = Field(default=None, ge=1)
    group_count: int | None = Field(default=None, ge=0)
    exact_coverage: bool = True


class ParseSummary(FrameworkModel):
    """Counts for parsing outcomes at the request level."""

    request_count: int = Field(default=0, ge=0)
    parsed_request_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)


class ValidationSummary(FrameworkModel):
    """Coverage validation summary for flattened annotations."""

    valid: bool = True
    exact_coverage: bool = True
    missing_unit_count: int = Field(default=0, ge=0)
    unexpected_unit_count: int = Field(default=0, ge=0)
    duplicate_unit_count: int = Field(default=0, ge=0)


class LineageSummary(FrameworkModel):
    """Optional lineage metadata linking a run to an earlier run."""

    parent_run_id: str | None = None
    parent_artifact_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunManifest(FrameworkModel):
    """Authoritative lifecycle record for a workflow run."""

    schema_version: str = "0.1.1"
    run_id: str = Field(min_length=1)
    run_name: str = Field(min_length=1)
    task_kind: TaskKind
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    components: ComponentIdentitySummary
    input_summary: InputSummary
    grouping_summary: GroupingSummary | None = None
    artifacts: dict[ArtifactKind, ArtifactRef] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    execution_handles: list[ExecutionHandle] = Field(default_factory=list)
    parse_summary: ParseSummary = Field(default_factory=ParseSummary)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    lineage: LineageSummary | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> "RunManifest":
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at"
            raise ValueError(msg)
        if self.completed_at is not None and self.started_at is not None and self.completed_at < self.started_at:
            msg = "completed_at cannot be earlier than started_at"
            raise ValueError(msg)
        for artifact_kind, artifact_ref in self.artifacts.items():
            if artifact_kind != artifact_ref.artifact_kind:
                msg = "artifact map keys must match the ArtifactRef.artifact_kind value"
                raise ValueError(msg)
        return self
