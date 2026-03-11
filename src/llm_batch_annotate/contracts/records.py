from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from pydantic import Field, field_validator, model_validator

from .._model import FrameworkModel
from ..enums import (
    ArtifactFormat,
    ArtifactKind,
    ExecutionStatus,
    FailureKind,
    ProviderKind,
)


class ComponentRef(FrameworkModel):
    import_path: str = Field(min_length=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(FrameworkModel):
    artifact_kind: ArtifactKind
    format: ArtifactFormat
    relative_path: str = Field(min_length=1)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if PurePosixPath(value).is_absolute():
            msg = "relative_path must be relative to the run directory"
            raise ValueError(msg)
        return value


class ProviderCapabilities(FrameworkModel):
    provider_kind: ProviderKind
    supports_batch_mode: bool = True
    supports_async_jobs: bool = True
    supports_structured_output: bool = False
    supports_strict_response_schema: bool = False
    max_request_count: int | None = Field(default=None, ge=1)
    max_file_size_bytes: int | None = Field(default=None, ge=1)
    grouping_constraints: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionHandle(FrameworkModel):
    provider_kind: ProviderKind
    job_id: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.PENDING
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    request_count: int | None = Field(default=None, ge=0)
    status_message: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ExecutionHandle":
        if self.submitted_at is not None and self.completed_at is not None and self.completed_at < self.submitted_at:
            msg = "completed_at cannot be earlier than submitted_at"
            raise ValueError(msg)
        return self


class UnitRecord(FrameworkModel):
    unit_id: str = Field(min_length=1)
    source_row_index: int | None = Field(default=None, ge=0)
    fields: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroupRecord(FrameworkModel):
    group_id: str = Field(min_length=1)
    unit_ids: list[str] = Field(min_length=1)
    group_index: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit_ids")
    @classmethod
    def validate_unit_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            msg = "unit_ids must be unique within a group"
            raise ValueError(msg)
        return value


class GroupMembershipRecord(FrameworkModel):
    group_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    member_index: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequestRecord(FrameworkModel):
    request_id: str = Field(min_length=1)
    group_id: str | None = None
    unit_ids: list[str] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit_ids")
    @classmethod
    def validate_unit_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            msg = "unit_ids must be unique within a request"
            raise ValueError(msg)
        return value


class RawResultRecord(FrameworkModel):
    request_id: str = Field(min_length=1)
    status: ExecutionStatus
    provider_kind: ProviderKind | None = None
    job_id: str | None = None
    result_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawOutputRecord(RawResultRecord):
    request_id: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.SUCCEEDED


class RawErrorRecord(RawResultRecord):
    request_id: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.FAILED
    error_type: str | None = None
    message: str = Field(min_length=1)


class ParsedRequestRecord(FrameworkModel):
    request_id: str = Field(min_length=1)
    group_id: str | None = None
    unit_ids: list[str] = Field(min_length=1)
    parsed_payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnnotationRecord(FrameworkModel):
    unit_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    group_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailureRecord(FrameworkModel):
    failure_kind: FailureKind
    message: str = Field(min_length=1)
    request_id: str | None = None
    unit_id: str | None = None
    group_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_traceability(self) -> "FailureRecord":
        if not any([self.request_id, self.unit_id, self.group_id, self.details]):
            msg = "failure records must retain at least one traceability field or details"
            raise ValueError(msg)
        return self
