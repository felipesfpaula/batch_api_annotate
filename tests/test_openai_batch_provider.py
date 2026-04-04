from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from llm_batch_annotate import ExecutionStatus, OpenAIBatchProvider, OpenAIBatchProviderError, RequestRecord
from llm_batch_annotate.configs import OpenAIBatchConfig


class FakeTransport:
    def __init__(self, *responses: tuple[int, Mapping[str, str], bytes]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def json_response(payload: Mapping[str, Any], status_code: int = 200) -> tuple[int, Mapping[str, str], bytes]:
    return status_code, {"content-type": "application/json"}, json.dumps(payload).encode("utf-8")


def text_response(text: str, status_code: int = 200) -> tuple[int, Mapping[str, str], bytes]:
    return status_code, {"content-type": "text/plain"}, text.encode("utf-8")


def make_batch(
    *,
    status: str,
    output_file_id: str | None = None,
    error_file_id: str | None = None,
    completed: int = 0,
    failed: int = 0,
) -> dict[str, Any]:
    return {
        "id": "batch_123",
        "object": "batch",
        "endpoint": "/v1/chat/completions",
        "input_file_id": "file_input_123",
        "completion_window": "24h",
        "status": status,
        "output_file_id": output_file_id,
        "error_file_id": error_file_id,
        "created_at": 1711471533,
        "completed_at": 1711471599 if status in {"completed", "failed"} else None,
        "failed_at": 1711471599 if status == "failed" else None,
        "expired_at": None,
        "cancelled_at": None,
        "request_counts": {
            "total": 2,
            "completed": completed,
            "failed": failed,
        },
        "metadata": {"description": "test batch"},
    }


def make_provider(transport: FakeTransport) -> OpenAIBatchProvider:
    return OpenAIBatchProvider(api_key="test-key", request_handler=transport)


def make_config(**request_options: Any) -> OpenAIBatchConfig:
    return OpenAIBatchConfig(
        model="gpt-4.1-mini",
        completion_window="24h",
        metadata={"run_name": "provider-test"},
        request_options=request_options,
    )


def test_submit_requests_uploads_jsonl_and_creates_batch() -> None:
    transport = FakeTransport(
        json_response({"id": "file_input_123", "object": "file"}),
        json_response(make_batch(status="validating")),
    )
    provider = make_provider(transport)
    config = make_config()

    handles = provider.submit_requests(
        [
            RequestRecord(
                request_id="request-1",
                group_id="group-1",
                unit_ids=["u-1"],
                payload={
                    "messages": [{"role": "user", "content": "Annotate row 1"}],
                    "metadata": {"builder": "simple"},
                },
                metadata={"row_id_column": "query_id", "row_ids": ["u-1"], "unit_ids": ["u-1"]},
            ),
            RequestRecord(
                request_id="request-2",
                group_id="group-2",
                unit_ids=["u-2"],
                payload={"messages": [{"role": "user", "content": "Annotate row 2"}]},
                metadata={"row_id_column": "query_id", "row_ids": ["u-2"], "unit_ids": ["u-2"]},
            ),
        ],
        config,
    )

    assert len(handles) == 1
    handle = handles[0]
    assert handle.status is ExecutionStatus.SUBMITTED
    assert handle.job_id == "batch_123"
    assert handle.request_count == 2
    assert handle.provider_metadata["input_file_id"] == "file_input_123"
    assert handle.metadata["request_context"]["request-1"]["group_id"] == "group-1"
    assert handle.metadata["request_context"]["request-1"]["row_id_column"] == "query_id"
    assert handle.metadata["request_context"]["request-1"]["row_ids"] == ["u-1"]
    assert handle.metadata["request_context"]["request-1"]["metadata"]["builder"] == "simple"

    upload_call = transport.calls[0]
    assert upload_call["method"] == "POST"
    assert upload_call["url"] == "https://api.openai.com/v1/files"
    assert "multipart/form-data" in upload_call["headers"]["Content-Type"]
    body_text = upload_call["body"].decode("utf-8")
    assert 'name="purpose"' in body_text
    assert '"custom_id":"request-1"' in body_text
    assert '"url":"/v1/chat/completions"' in body_text
    assert '"model":"gpt-4.1-mini"' in body_text
    assert '"messages":[{"content":"Annotate row 1","role":"user"}]' in body_text
    assert '"builder":"simple"' not in body_text

    create_call = transport.calls[1]
    assert create_call["url"] == "https://api.openai.com/v1/batches"
    create_payload = json.loads(create_call["body"].decode("utf-8"))
    assert create_payload == {
        "completion_window": "24h",
        "endpoint": "/v1/chat/completions",
        "input_file_id": "file_input_123",
        "metadata": {"run_name": "provider-test"},
    }


def test_poll_status_maps_completed_batch_with_failures_to_partial() -> None:
    transport = FakeTransport(
        json_response(make_batch(status="completed", output_file_id="file_out_123", error_file_id="file_err_123", completed=1, failed=1))
    )
    provider = make_provider(transport)
    config = make_config()

    handle = provider.build_handle(
        "batch_123",
        status=ExecutionStatus.SUBMITTED,
        submitted_at=datetime(2026, 3, 11, 12, 0, tzinfo=UTC),
        request_count=2,
    )
    updated = provider.poll_status(handle, config)

    assert updated.status is ExecutionStatus.PARTIAL
    assert updated.completed_at == datetime.fromtimestamp(1711471599, tz=UTC)
    assert updated.provider_metadata["output_file_id"] == "file_out_123"
    assert updated.provider_metadata["error_file_id"] == "file_err_123"
    assert updated.provider_metadata["request_counts"] == {"total": 2, "completed": 1, "failed": 1}


def test_retrieve_outputs_normalizes_chat_completion_lines() -> None:
    transport = FakeTransport(
        text_response(
            '\n'.join(
                [
                    json.dumps(
                        {
                            "id": "batch_req_1",
                            "custom_id": "request-1",
                            "response": {
                                "status_code": 200,
                                "request_id": "req_1",
                                "body": {
                                    "id": "chatcmpl_1",
                                    "object": "chat.completion",
                                    "choices": [
                                        {
                                            "index": 0,
                                            "message": {
                                                "role": "assistant",
                                                "content": '{"items":[{"unit_id":"u-1","label":"keep"}]}',
                                            },
                                            "finish_reason": "stop",
                                        }
                                    ],
                                },
                            },
                            "error": None,
                        }
                    )
                ]
            )
        )
    )
    provider = make_provider(transport)
    config = make_config()
    handle = provider.build_handle(
        "batch_123",
        status=ExecutionStatus.PARTIAL,
        provider_metadata={"batch": make_batch(status="completed", output_file_id="file_out_123", completed=1, failed=1)},
        metadata={
            "request_context": {
                "request-1": {
                    "group_id": "group-1",
                    "row_id_column": "query_id",
                    "row_ids": ["u-1"],
                    "unit_ids": ["u-1"],
                    "metadata": {"source": "tests"},
                }
            }
        },
    )

    outputs = provider.retrieve_outputs(handle, config)

    assert len(outputs) == 1
    output = outputs[0]
    assert output.request_id == "request-1"
    assert output.provider_kind.value == "openai_batch"
    assert output.provider_metadata["openai_request_id"] == "req_1"
    assert output.payload["content"] == '{"items":[{"unit_id":"u-1","label":"keep"}]}'
    assert output.payload["response"]["id"] == "chatcmpl_1"
    assert output.metadata["group_id"] == "group-1"
    assert output.metadata["row_id_column"] == "query_id"
    assert output.metadata["row_ids"] == ["u-1"]
    assert output.metadata["unit_ids"] == ["u-1"]
    assert output.metadata["source"] == "tests"


def test_retrieve_outputs_normalizes_responses_api_lines() -> None:
    transport = FakeTransport(
        text_response(
            '\n'.join(
                [
                    json.dumps(
                        {
                            "id": "batch_req_1",
                            "custom_id": "request-1",
                            "response": {
                                "status_code": 200,
                                "request_id": "req_1",
                                "body": {
                                    "id": "resp_1",
                                    "object": "response",
                                    "output": [
                                        {"id": "rs_1", "type": "reasoning", "summary": []},
                                        {
                                            "id": "msg_1",
                                            "type": "message",
                                            "status": "completed",
                                            "role": "assistant",
                                            "content": [
                                                {
                                                    "type": "output_text",
                                                    "text": '{"items":[{"unit_id":"u-1","query":"red shoes"}]}',
                                                    "annotations": [],
                                                }
                                            ],
                                        },
                                    ],
                                },
                            },
                            "error": None,
                        }
                    )
                ]
            )
        )
    )
    provider = make_provider(transport)
    config = make_config(endpoint="/v1/responses")
    handle = provider.build_handle(
        "batch_123",
        status=ExecutionStatus.SUCCEEDED,
        provider_metadata={
            "batch": {
                **make_batch(status="completed", output_file_id="file_out_123", completed=1),
                "endpoint": "/v1/responses",
            }
        },
        metadata={
            "request_context": {
                "request-1": {
                    "group_id": "group-1",
                    "row_id_column": "query_id",
                    "row_ids": ["u-1"],
                    "unit_ids": ["u-1"],
                    "metadata": {"source": "tests"},
                }
            }
        },
    )

    outputs = provider.retrieve_outputs(handle, config)

    assert len(outputs) == 1
    output = outputs[0]
    assert output.request_id == "request-1"
    assert output.payload["content"] == '{"items":[{"unit_id":"u-1","query":"red shoes"}]}'
    assert output.payload["response"]["id"] == "resp_1"
    assert output.provider_metadata["endpoint"] == "/v1/responses"


def test_retrieve_errors_normalizes_error_file_lines() -> None:
    transport = FakeTransport(
        text_response(
            '\n'.join(
                [
                    json.dumps(
                        {
                            "id": "batch_req_2",
                            "custom_id": "request-2",
                            "response": None,
                            "error": {
                                "code": "batch_expired",
                                "message": "This request could not be executed before the completion window expired.",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "id": "batch_req_3",
                            "custom_id": "request-3",
                            "response": {
                                "status_code": 400,
                                "request_id": "req_3",
                                "body": {
                                    "error": {
                                        "message": "Invalid request payload",
                                        "type": "invalid_request_error",
                                    }
                                },
                            },
                            "error": None,
                        }
                    ),
                ]
            )
        )
    )
    provider = make_provider(transport)
    config = make_config()
    handle = provider.build_handle(
        "batch_123",
        status=ExecutionStatus.PARTIAL,
        provider_metadata={"batch": make_batch(status="expired", error_file_id="file_err_123", completed=1, failed=1)},
        metadata={
            "request_context": {
                "request-2": {
                    "group_id": "group-2",
                    "row_id_column": "query_id",
                    "row_ids": ["u-2"],
                    "unit_ids": ["u-2"],
                    "metadata": {},
                },
                "request-3": {
                    "group_id": "group-3",
                    "row_id_column": "query_id",
                    "row_ids": ["u-3"],
                    "unit_ids": ["u-3"],
                    "metadata": {"note": "bad payload"},
                },
            }
        },
    )

    errors = provider.retrieve_errors(handle, config)

    assert len(errors) == 2
    assert errors[0].request_id == "request-2"
    assert errors[0].error_type == "batch_expired"
    assert "completion window expired" in errors[0].message
    assert errors[1].request_id == "request-3"
    assert errors[1].error_type == "invalid_request_error"
    assert errors[1].provider_metadata["status_code"] == 400
    assert errors[1].metadata["note"] == "bad payload"


def test_provider_rejects_unsupported_completion_window() -> None:
    provider = make_provider(FakeTransport())

    with pytest.raises(ValueError, match="completion_window='24h'"):
        provider.validate_provider_config(OpenAIBatchConfig(model="gpt-4.1-mini", completion_window="1h"))


def test_provider_raises_api_errors_with_openai_message() -> None:
    transport = FakeTransport(
        json_response({"error": {"message": "The API key is invalid"}}, status_code=401)
    )
    provider = make_provider(transport)
    config = make_config()

    with pytest.raises(OpenAIBatchProviderError, match="The API key is invalid"):
        provider.submit_requests(
            [RequestRecord(request_id="request-1", unit_ids=["u-1"], payload={"messages": [{"role": "user", "content": "x"}]})],
            config,
        )
