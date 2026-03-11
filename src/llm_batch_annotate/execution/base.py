from __future__ import annotations

from abc import ABC
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ..configs.models import BaseProviderConfig
from ..contracts.base import ExecutionProvider
from ..contracts.records import (
    ExecutionHandle,
    ProviderCapabilities,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
)
from ..enums import ExecutionStatus, ProviderKind

_STATUS_ALIASES: dict[str, ExecutionStatus] = {
    "pending": ExecutionStatus.PENDING,
    "queued": ExecutionStatus.PENDING,
    "submitted": ExecutionStatus.SUBMITTED,
    "created": ExecutionStatus.SUBMITTED,
    "running": ExecutionStatus.RUNNING,
    "in_progress": ExecutionStatus.RUNNING,
    "processing": ExecutionStatus.RUNNING,
    "succeeded": ExecutionStatus.SUCCEEDED,
    "success": ExecutionStatus.SUCCEEDED,
    "completed": ExecutionStatus.SUCCEEDED,
    "complete": ExecutionStatus.SUCCEEDED,
    "failed": ExecutionStatus.FAILED,
    "error": ExecutionStatus.FAILED,
    "cancelled": ExecutionStatus.CANCELLED,
    "canceled": ExecutionStatus.CANCELLED,
    "partial": ExecutionStatus.PARTIAL,
    "partially_failed": ExecutionStatus.PARTIAL,
}

TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.PARTIAL,
    }
)

SUCCESSFUL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.PARTIAL,
    }
)


def normalize_execution_status(status: ExecutionStatus | str) -> ExecutionStatus:
    if isinstance(status, ExecutionStatus):
        return status
    normalized_key = status.strip().lower().replace("-", "_").replace(" ", "_")
    normalized_status = _STATUS_ALIASES.get(normalized_key)
    if normalized_status is None:
        msg = f"unsupported execution status: {status!r}"
        raise ValueError(msg)
    return normalized_status


def is_terminal_execution_status(status: ExecutionStatus | str) -> bool:
    return normalize_execution_status(status) in TERMINAL_EXECUTION_STATUSES


def is_successful_execution_status(status: ExecutionStatus | str) -> bool:
    return normalize_execution_status(status) in SUCCESSFUL_EXECUTION_STATUSES


class ExecutionProviderBase(ExecutionProvider, ABC):
    def __init__(
        self,
        *,
        provider_kind: ProviderKind,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        if capabilities is not None and capabilities.provider_kind is not provider_kind:
            msg = "provider capabilities must match the provider implementation kind"
            raise ValueError(msg)
        self._provider_kind = provider_kind
        self._capabilities = capabilities or ProviderCapabilities(provider_kind=provider_kind)

    @property
    def provider_kind(self) -> ProviderKind:
        return self._provider_kind

    def validate_provider_config(self, config: BaseProviderConfig) -> None:
        if config.provider_kind is not self.provider_kind:
            msg = (
                "provider config kind does not match provider implementation: "
                f"expected {self.provider_kind.value!r}, got {config.provider_kind.value!r}"
            )
            raise ValueError(msg)

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities.model_copy(deep=True)

    def ensure_handle_provider(self, handle: ExecutionHandle) -> ExecutionHandle:
        if handle.provider_kind is not self.provider_kind:
            msg = (
                "execution handle kind does not match provider implementation: "
                f"expected {self.provider_kind.value!r}, got {handle.provider_kind.value!r}"
            )
            raise ValueError(msg)
        return handle

    def build_handle(
        self,
        job_id: str,
        *,
        status: ExecutionStatus | str = ExecutionStatus.PENDING,
        submitted_at: datetime | None = None,
        completed_at: datetime | None = None,
        request_count: int | None = None,
        status_message: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionHandle:
        return ExecutionHandle(
            provider_kind=self.provider_kind,
            job_id=job_id,
            status=normalize_execution_status(status),
            submitted_at=submitted_at,
            completed_at=completed_at,
            request_count=request_count,
            status_message=status_message,
            provider_metadata=dict(provider_metadata or {}),
            metadata=dict(metadata or {}),
        )

    def update_handle(
        self,
        handle: ExecutionHandle,
        *,
        status: ExecutionStatus | str | None = None,
        submitted_at: datetime | None = None,
        completed_at: datetime | None = None,
        request_count: int | None = None,
        status_message: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionHandle:
        current_handle = self.ensure_handle_provider(handle)
        merged_provider_metadata = dict(current_handle.provider_metadata)
        merged_provider_metadata.update(provider_metadata or {})
        merged_metadata = dict(current_handle.metadata)
        merged_metadata.update(metadata or {})
        return ExecutionHandle(
            provider_kind=self.provider_kind,
            job_id=current_handle.job_id,
            status=normalize_execution_status(status or current_handle.status),
            submitted_at=submitted_at if submitted_at is not None else current_handle.submitted_at,
            completed_at=completed_at if completed_at is not None else current_handle.completed_at,
            request_count=request_count if request_count is not None else current_handle.request_count,
            status_message=status_message if status_message is not None else current_handle.status_message,
            provider_metadata=merged_provider_metadata,
            metadata=merged_metadata,
        )

    def build_raw_output(
        self,
        request_id: str,
        *,
        status: ExecutionStatus | str = ExecutionStatus.SUCCEEDED,
        job_id: str | None = None,
        result_id: str | None = None,
        payload: dict[str, Any] | None = None,
        received_at: datetime | None = None,
        provider_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RawOutputRecord:
        return RawOutputRecord(
            request_id=request_id,
            status=normalize_execution_status(status),
            provider_kind=self.provider_kind,
            job_id=job_id,
            result_id=result_id,
            payload=dict(payload or {}),
            received_at=received_at,
            provider_metadata=dict(provider_metadata or {}),
            metadata=dict(metadata or {}),
        )

    def build_raw_error(
        self,
        request_id: str,
        message: str,
        *,
        status: ExecutionStatus | str = ExecutionStatus.FAILED,
        job_id: str | None = None,
        result_id: str | None = None,
        error_type: str | None = None,
        payload: dict[str, Any] | None = None,
        received_at: datetime | None = None,
        provider_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RawErrorRecord:
        return RawErrorRecord(
            request_id=request_id,
            status=normalize_execution_status(status),
            provider_kind=self.provider_kind,
            job_id=job_id,
            result_id=result_id,
            error_type=error_type,
            message=message,
            payload=dict(payload or {}),
            received_at=received_at,
            provider_metadata=dict(provider_metadata or {}),
            metadata=dict(metadata or {}),
        )

    def validate_request_batch(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> None:
        self.validate_provider_config(config)
        if not requests:
            msg = "execution providers require at least one request to submit"
            raise ValueError(msg)

        seen_request_ids: set[str] = set()
        duplicate_request_ids: set[str] = set()
        for request in requests:
            if request.request_id in seen_request_ids:
                duplicate_request_ids.add(request.request_id)
            seen_request_ids.add(request.request_id)

        if duplicate_request_ids:
            duplicates = sorted(duplicate_request_ids)
            msg = f"request ids must be unique within a provider submission: {duplicates}"
            raise ValueError(msg)

        max_request_count = self._capabilities.max_request_count
        if max_request_count is not None and len(requests) > max_request_count:
            msg = (
                "request batch exceeds provider capabilities: "
                f"{len(requests)} requests submitted, limit is {max_request_count}"
            )
            raise ValueError(msg)


__all__ = [
    "ExecutionProvider",
    "ExecutionProviderBase",
    "SUCCESSFUL_EXECUTION_STATUSES",
    "TERMINAL_EXECUTION_STATUSES",
    "is_successful_execution_status",
    "is_terminal_execution_status",
    "normalize_execution_status",
]
