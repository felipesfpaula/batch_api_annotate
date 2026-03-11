from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from llm_batch_annotate import (
    ExecutionHandle,
    ExecutionProviderBase,
    ExecutionStatus,
    ProviderCapabilities,
    ProviderKind,
    RawErrorRecord,
    RawOutputRecord,
    RawResultRecord,
    RequestRecord,
    is_successful_execution_status,
    is_terminal_execution_status,
    normalize_execution_status,
)
from llm_batch_annotate.configs import BaseProviderConfig, GenericProviderConfig


class FakeExecutionProvider(ExecutionProviderBase):
    def __init__(self) -> None:
        super().__init__(
            provider_kind=ProviderKind.CUSTOM,
            capabilities=ProviderCapabilities(
                provider_kind=ProviderKind.CUSTOM,
                max_request_count=2,
                supports_structured_output=True,
            ),
        )

    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        self.validate_request_batch(requests, config)
        return [
            self.build_handle(
                "job-1",
                status="submitted",
                submitted_at=datetime(2026, 3, 11, 12, 0, tzinfo=UTC),
                request_count=len(requests),
            )
        ]

    def poll_status(self, handle: ExecutionHandle, config: BaseProviderConfig) -> ExecutionHandle:
        self.validate_provider_config(config)
        return self.update_handle(
            handle,
            status="running",
            status_message="provider accepted batch",
            provider_metadata={"poll_count": 1},
        )

    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        return [
            self.build_raw_output(
                "request-1",
                job_id=handle.job_id,
                result_id="result-1",
                payload={"content": '{"items":[{"unit_id":"u-1"}]}'},
            )
        ]

    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        return [
            self.build_raw_error(
                "request-2",
                "provider execution failed",
                job_id=handle.job_id,
                result_id="result-2",
                error_type="provider_error",
            )
        ]


def test_normalize_execution_status_supports_common_aliases() -> None:
    assert normalize_execution_status("queued") is ExecutionStatus.PENDING
    assert normalize_execution_status("in-progress") is ExecutionStatus.RUNNING
    assert normalize_execution_status("completed") is ExecutionStatus.SUCCEEDED
    assert normalize_execution_status("canceled") is ExecutionStatus.CANCELLED
    assert normalize_execution_status(ExecutionStatus.PARTIAL) is ExecutionStatus.PARTIAL


def test_normalize_execution_status_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="unsupported execution status"):
        normalize_execution_status("mystery")


def test_terminal_and_success_helpers_cover_partial_status() -> None:
    assert is_terminal_execution_status("partial") is True
    assert is_successful_execution_status("partial") is True
    assert is_terminal_execution_status("running") is False
    assert is_successful_execution_status("failed") is False


def test_execution_handle_validates_timestamp_order() -> None:
    with pytest.raises(ValueError, match="completed_at cannot be earlier"):
        ExecutionHandle(
            provider_kind=ProviderKind.CUSTOM,
            job_id="job-1",
            submitted_at=datetime(2026, 3, 11, 13, 0, tzinfo=UTC),
            completed_at=datetime(2026, 3, 11, 12, 0, tzinfo=UTC),
        )


def test_raw_result_records_capture_normalized_provider_metadata() -> None:
    result = RawResultRecord(
        request_id="request-1",
        status=ExecutionStatus.SUCCEEDED,
        provider_kind=ProviderKind.CUSTOM,
        job_id="job-1",
        result_id="result-1",
        payload={"ok": True},
        provider_metadata={"provider_request_id": "abc"},
        metadata={"source": "test"},
    )

    assert result.provider_kind is ProviderKind.CUSTOM
    assert result.job_id == "job-1"
    assert result.result_id == "result-1"
    assert result.provider_metadata["provider_request_id"] == "abc"
    assert result.metadata["source"] == "test"


def test_execution_provider_base_builds_handles_and_raw_records() -> None:
    provider = FakeExecutionProvider()
    config = GenericProviderConfig()

    handles = provider.submit_requests(
        [
            RequestRecord(request_id="request-1", unit_ids=["u-1"]),
            RequestRecord(request_id="request-2", unit_ids=["u-2"]),
        ],
        config,
    )
    handle = provider.poll_status(handles[0], config)
    outputs = provider.retrieve_outputs(handle, config)
    errors = provider.retrieve_errors(handle, config)

    assert handles[0].provider_kind is ProviderKind.CUSTOM
    assert handles[0].status is ExecutionStatus.SUBMITTED
    assert handle.status is ExecutionStatus.RUNNING
    assert handle.provider_metadata["poll_count"] == 1
    assert outputs[0].provider_kind is ProviderKind.CUSTOM
    assert outputs[0].status is ExecutionStatus.SUCCEEDED
    assert outputs[0].job_id == "job-1"
    assert errors[0].provider_kind is ProviderKind.CUSTOM
    assert errors[0].status is ExecutionStatus.FAILED
    assert errors[0].error_type == "provider_error"


def test_execution_provider_base_validates_provider_kind_and_batch_size() -> None:
    provider = FakeExecutionProvider()

    with pytest.raises(ValueError, match="expected 'custom', got 'openai_batch'"):
        provider.validate_provider_config(BaseProviderConfig(provider_kind=ProviderKind.OPENAI_BATCH))

    with pytest.raises(ValueError, match="limit is 2"):
        provider.validate_request_batch(
            [
                RequestRecord(request_id="request-1", unit_ids=["u-1"]),
                RequestRecord(request_id="request-2", unit_ids=["u-2"]),
                RequestRecord(request_id="request-3", unit_ids=["u-3"]),
            ],
            GenericProviderConfig(),
        )


def test_execution_provider_base_validates_duplicate_request_ids() -> None:
    provider = FakeExecutionProvider()

    with pytest.raises(ValueError, match="request ids must be unique"):
        provider.validate_request_batch(
            [
                RequestRecord(request_id="request-1", unit_ids=["u-1"]),
                RequestRecord(request_id="request-1", unit_ids=["u-2"]),
            ],
            GenericProviderConfig(),
        )
