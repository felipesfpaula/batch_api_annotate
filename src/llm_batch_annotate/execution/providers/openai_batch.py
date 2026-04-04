"""OpenAI Batch execution provider implementation."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ...configs.models import BaseProviderConfig, OpenAIBatchConfig
from ...contracts.records import ExecutionHandle, ProviderCapabilities, RawErrorRecord, RawOutputRecord, RequestRecord
from ...enums import ExecutionStatus, ProviderKind
from ..base import ExecutionProviderBase

_RequestHandler = Callable[
    [str, str, Mapping[str, str], bytes | None, float],
    tuple[int, Mapping[str, str], bytes],
]

_DEFAULT_BASE_URL = "https://api.openai.com"
_DEFAULT_TIMEOUT_SECONDS = 60.0
_SUPPORTED_ENDPOINTS = frozenset({"/v1/chat/completions", "/v1/responses"})
_OPENAI_TERMINAL_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})


class OpenAIBatchProviderError(RuntimeError):
    """Raised when the OpenAI Batch provider cannot complete an API operation."""


class OpenAIBatchProvider(ExecutionProviderBase):
    """Submit, poll, and retrieve batch jobs from the OpenAI Batch API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        request_handler: _RequestHandler | None = None,
    ) -> None:
        super().__init__(
            provider_kind=ProviderKind.OPENAI_BATCH,
            capabilities=ProviderCapabilities(
                provider_kind=ProviderKind.OPENAI_BATCH,
                supports_batch_mode=True,
                supports_async_jobs=True,
                supports_structured_output=True,
                supports_strict_response_schema=False,
                max_request_count=50_000,
                max_file_size_bytes=200_000_000,
                grouping_constraints={},
                provider_metadata={
                    "supported_batch_endpoints": sorted(_SUPPORTED_ENDPOINTS),
                    "completion_windows": ["24h"],
                },
            ),
        )
        self.api_key = api_key
        self.organization = organization
        self.project = project
        self.timeout_seconds = timeout_seconds
        self._request_handler = request_handler or self._urllib_request

    def validate_provider_config(self, config: BaseProviderConfig) -> None:
        super().validate_provider_config(config)
        if not isinstance(config, OpenAIBatchConfig):
            msg = "OpenAIBatchProvider requires OpenAIBatchConfig"
            raise TypeError(msg)
        if config.completion_window != "24h":
            msg = "OpenAI Batch currently only supports completion_window='24h'"
            raise ValueError(msg)
        endpoint = self._resolve_endpoint(config)
        if endpoint not in _SUPPORTED_ENDPOINTS:
            supported = ", ".join(sorted(_SUPPORTED_ENDPOINTS))
            msg = f"unsupported OpenAI Batch endpoint {endpoint!r}; supported endpoints: {supported}"
            raise ValueError(msg)

    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        self.validate_request_batch(requests, config)
        openai_config = self._coerce_config(config)

        input_lines, request_context = self._build_input_file(requests, openai_config)
        encoded_input = input_lines.encode("utf-8")
        max_file_size = self.get_capabilities().max_file_size_bytes
        if max_file_size is not None and len(encoded_input) > max_file_size:
            msg = (
                "OpenAI Batch input file exceeds the documented size limit: "
                f"{len(encoded_input)} bytes > {max_file_size} bytes"
            )
            raise ValueError(msg)

        uploaded_file = self._upload_input_file(encoded_input, openai_config)
        batch = self._create_batch(uploaded_file["id"], openai_config)
        return [
            self.build_handle(
                batch["id"],
                status=self._normalize_batch_status(batch),
                submitted_at=self._timestamp_from_batch(batch, "created_at"),
                completed_at=self._completed_timestamp_from_batch(batch),
                request_count=self._request_total(batch, default=len(requests)),
                status_message=str(batch.get("status", "submitted")),
                provider_metadata=self._handle_provider_metadata(batch),
                metadata={"request_context": request_context},
            )
        ]

    def poll_status(self, handle: ExecutionHandle, config: BaseProviderConfig) -> ExecutionHandle:
        self.validate_provider_config(config)
        current_handle = self.ensure_handle_provider(handle)
        batch = self._retrieve_batch(current_handle.job_id, self._coerce_config(config))
        return self.update_handle(
            current_handle,
            status=self._normalize_batch_status(batch),
            submitted_at=self._timestamp_from_batch(batch, "created_at"),
            completed_at=self._completed_timestamp_from_batch(batch),
            request_count=self._request_total(batch, default=current_handle.request_count),
            status_message=str(batch.get("status", current_handle.status.value)),
            provider_metadata=self._handle_provider_metadata(batch),
        )

    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        self.validate_provider_config(config)
        current_handle = self.ensure_handle_provider(handle)
        batch = self._batch_for_retrieval(current_handle, self._coerce_config(config))
        output_file_id = batch.get("output_file_id")
        if not output_file_id:
            return []

        request_context = self._request_context_from_handle(current_handle)
        output_lines = self._download_jsonl_file(str(output_file_id), self._coerce_config(config))
        records: list[RawOutputRecord] = []
        for line in output_lines:
            record = self._line_to_raw_output(line, batch=batch, request_context=request_context)
            if record is not None:
                records.append(record)
        return records

    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        self.validate_provider_config(config)
        current_handle = self.ensure_handle_provider(handle)
        batch = self._batch_for_retrieval(current_handle, self._coerce_config(config))
        error_file_id = batch.get("error_file_id")
        if not error_file_id:
            return []

        request_context = self._request_context_from_handle(current_handle)
        error_lines = self._download_jsonl_file(str(error_file_id), self._coerce_config(config))
        records: list[RawErrorRecord] = []
        for line in error_lines:
            record = self._line_to_raw_error(line, batch=batch, request_context=request_context)
            if record is not None:
                records.append(record)
        return records

    def _coerce_config(self, config: BaseProviderConfig) -> OpenAIBatchConfig:
        self.validate_provider_config(config)
        return config

    def _resolve_api_key(self, config: OpenAIBatchConfig) -> str:
        request_options = config.request_options
        api_key = request_options.get("api_key") or self.api_key
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()

        env_var_name = str(request_options.get("api_key_env_var", "OPENAI_API_KEY"))
        env_api_key = os.getenv(env_var_name)
        if env_api_key:
            return env_api_key.strip()

        msg = f"OpenAI API key is required; set {env_var_name} or pass api_key"
        raise ValueError(msg)

    def _resolve_base_url(self, config: OpenAIBatchConfig) -> str:
        return (config.api_base or _DEFAULT_BASE_URL).rstrip("/")

    def _resolve_timeout(self, config: OpenAIBatchConfig) -> float:
        timeout = config.request_options.get("timeout_seconds", self.timeout_seconds)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError) as exc:
            msg = "timeout_seconds must be numeric"
            raise ValueError(msg) from exc
        if timeout_value <= 0:
            msg = "timeout_seconds must be greater than zero"
            raise ValueError(msg)
        return timeout_value

    def _resolve_endpoint(self, config: OpenAIBatchConfig) -> str:
        endpoint = str(config.request_options.get("endpoint", "/v1/chat/completions"))
        return endpoint.strip()

    def _base_headers(self, config: OpenAIBatchConfig) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._resolve_api_key(config)}",
            "Accept": "application/json",
        }
        organization = config.request_options.get("organization") or self.organization
        if organization:
            headers["OpenAI-Organization"] = str(organization)
        project = config.request_options.get("project") or self.project
        if project:
            headers["OpenAI-Project"] = str(project)
        extra_headers = config.request_options.get("headers", {})
        if extra_headers:
            if not isinstance(extra_headers, Mapping):
                msg = "request_options.headers must be a mapping"
                raise ValueError(msg)
            headers.update({str(key): str(value) for key, value in extra_headers.items()})
        return headers

    def _build_url(self, config: OpenAIBatchConfig, path: str) -> str:
        base_url = self._resolve_base_url(config)
        if base_url.endswith("/v1") and path.startswith("/v1/"):
            return f"{base_url}{path[3:]}"
        return f"{base_url}{path}"

    def _request_json(
        self,
        method: str,
        path: str,
        config: OpenAIBatchConfig,
        *,
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        request_headers = dict(self._base_headers(config))
        request_headers["Content-Type"] = "application/json"
        if headers is not None:
            request_headers.update(headers)

        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        status_code, _, response_body = self._request_handler(
            method,
            self._build_url(config, path),
            request_headers,
            body,
            self._resolve_timeout(config),
        )
        return self._decode_json_response(status_code, response_body)

    def _request_bytes(
        self,
        method: str,
        path: str,
        config: OpenAIBatchConfig,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> bytes:
        request_headers = dict(self._base_headers(config))
        if headers is not None:
            request_headers.update(headers)
        status_code, _, response_body = self._request_handler(
            method,
            self._build_url(config, path),
            request_headers,
            body,
            self._resolve_timeout(config),
        )
        if status_code >= 400:
            self._raise_api_error(status_code, response_body)
        return response_body

    def _upload_input_file(self, encoded_input: bytes, config: OpenAIBatchConfig) -> Mapping[str, Any]:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="purpose"\r\n\r\n'
            "batch\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="batch-input.jsonl"\r\n'
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode("utf-8") + encoded_input + f"\r\n--{boundary}--\r\n".encode("utf-8")
        response = self._request_bytes(
            "POST",
            "/v1/files",
            config,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            body=body,
        )
        return self._decode_json_response(200, response)

    def _create_batch(self, input_file_id: str, config: OpenAIBatchConfig) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "input_file_id": input_file_id,
            "endpoint": self._resolve_endpoint(config),
            "completion_window": config.completion_window,
        }
        if config.metadata:
            payload["metadata"] = {str(key): str(value) for key, value in config.metadata.items()}
        return self._request_json("POST", "/v1/batches", config, payload=payload)

    def _retrieve_batch(self, batch_id: str, config: OpenAIBatchConfig) -> Mapping[str, Any]:
        return self._request_json("GET", f"/v1/batches/{batch_id}", config)

    def _batch_for_retrieval(self, handle: ExecutionHandle, config: OpenAIBatchConfig) -> Mapping[str, Any]:
        provider_metadata = dict(handle.provider_metadata)
        batch = provider_metadata.get("batch")
        if isinstance(batch, Mapping):
            normalized_batch = dict(batch)
            if str(normalized_batch.get("status", "")) not in _OPENAI_TERMINAL_STATUSES:
                return dict(self._retrieve_batch(handle.job_id, config))
            return normalized_batch
        return dict(self._retrieve_batch(handle.job_id, config))

    def _download_jsonl_file(self, file_id: str, config: OpenAIBatchConfig) -> list[dict[str, Any]]:
        file_content = self._request_bytes("GET", f"/v1/files/{file_id}/content", config)
        lines: list[dict[str, Any]] = []
        for raw_line in file_content.decode("utf-8").splitlines():
            text = raw_line.strip()
            if not text:
                continue
            parsed_line = json.loads(text)
            if not isinstance(parsed_line, Mapping):
                msg = "OpenAI Batch result lines must decode to mappings"
                raise OpenAIBatchProviderError(msg)
            lines.append(dict(parsed_line))
        return lines

    def _build_input_file(
        self,
        requests: Sequence[RequestRecord],
        config: OpenAIBatchConfig,
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        endpoint = self._resolve_endpoint(config)
        line_defaults = config.request_options.get("body", {})
        if line_defaults and not isinstance(line_defaults, Mapping):
            msg = "request_options.body must be a mapping"
            raise ValueError(msg)

        request_context: dict[str, dict[str, Any]] = {}
        lines: list[str] = []
        for request in requests:
            line, context_entry = self._build_input_line(request, config, endpoint=endpoint, line_defaults=line_defaults)
            lines.append(json.dumps(line, separators=(",", ":"), sort_keys=True))
            request_context[request.request_id] = context_entry
        return "\n".join(lines) + "\n", request_context

    def _build_input_line(
        self,
        request: RequestRecord,
        config: OpenAIBatchConfig,
        *,
        endpoint: str,
        line_defaults: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(request.payload, Mapping):
            msg = "request payload must be a mapping for OpenAI Batch"
            raise ValueError(msg)

        payload_body = dict(request.payload)
        payload_metadata = payload_body.pop("metadata", {})
        if payload_metadata and not isinstance(payload_metadata, Mapping):
            msg = "request payload metadata must be a mapping when present"
            raise ValueError(msg)

        body = dict(line_defaults)
        body.update(payload_body)
        if endpoint == "/v1/responses" and "input" not in body and "messages" in body:
            body["input"] = body.pop("messages")

        if "model" in body and str(body["model"]) != config.model:
            msg = "OpenAI Batch input files must contain requests for a single configured model"
            raise ValueError(msg)
        body["model"] = config.model

        if endpoint == "/v1/chat/completions" and "messages" not in body:
            msg = "chat completions batch requests require a 'messages' field"
            raise ValueError(msg)
        if endpoint == "/v1/responses" and "input" not in body:
            msg = "responses batch requests require an 'input' field"
            raise ValueError(msg)

        line = {
            "custom_id": request.request_id,
            "method": "POST",
            "url": endpoint,
            "body": body,
        }
        merged_metadata = {
            **dict(request.metadata),
            **dict(payload_metadata),
        }
        raw_row_ids = merged_metadata.get("row_ids", request.unit_ids)
        if isinstance(raw_row_ids, Sequence) and not isinstance(raw_row_ids, (str, bytes, bytearray)):
            row_ids = [str(row_id) for row_id in raw_row_ids]
        else:
            row_ids = [str(unit_id) for unit_id in request.unit_ids]
        context_entry = {
            "group_id": request.group_id,
            "row_id_column": merged_metadata.get("row_id_column"),
            "row_ids": row_ids,
            "unit_ids": list(request.unit_ids),
            "metadata": merged_metadata,
        }
        return line, context_entry

    def _request_context_from_handle(self, handle: ExecutionHandle) -> dict[str, dict[str, Any]]:
        request_context = handle.metadata.get("request_context", {})
        if not isinstance(request_context, Mapping):
            return {}
        return {
            str(request_id): dict(context)
            for request_id, context in request_context.items()
            if isinstance(context, Mapping)
        }

    def _line_to_raw_output(
        self,
        line: Mapping[str, Any],
        *,
        batch: Mapping[str, Any],
        request_context: Mapping[str, Mapping[str, Any]],
    ) -> RawOutputRecord | None:
        response = line.get("response")
        if not isinstance(response, Mapping):
            return None
        status_code = int(response.get("status_code", 0) or 0)
        if status_code >= 400:
            return None

        request_id = str(line.get("custom_id", "")).strip()
        if not request_id:
            msg = "OpenAI Batch output lines must include custom_id"
            raise OpenAIBatchProviderError(msg)
        response_body = response.get("body", {})
        if not isinstance(response_body, Mapping):
            msg = "OpenAI Batch response bodies must be mappings"
            raise OpenAIBatchProviderError(msg)

        context = dict(request_context.get(request_id, {}))
        metadata = self._result_metadata_from_context(context)
        payload: dict[str, Any] = {"response": dict(response_body)}
        content = self._extract_response_content(response_body)
        if content is not None:
            payload["content"] = content

        return self.build_raw_output(
            request_id,
            job_id=str(batch.get("id", "")) or None,
            result_id=str(line.get("id", "")) or None,
            payload=payload,
            provider_metadata={
                "batch_line_id": line.get("id"),
                "openai_request_id": response.get("request_id"),
                "status_code": status_code,
                "endpoint": batch.get("endpoint"),
            },
            metadata=metadata,
        )

    def _line_to_raw_error(
        self,
        line: Mapping[str, Any],
        *,
        batch: Mapping[str, Any],
        request_context: Mapping[str, Mapping[str, Any]],
    ) -> RawErrorRecord | None:
        request_id = str(line.get("custom_id", "")).strip()
        if not request_id:
            msg = "OpenAI Batch error lines must include custom_id"
            raise OpenAIBatchProviderError(msg)

        context = dict(request_context.get(request_id, {}))
        metadata = self._result_metadata_from_context(context)
        provider_metadata: dict[str, Any] = {
            "batch_line_id": line.get("id"),
            "endpoint": batch.get("endpoint"),
        }

        error_payload = line.get("error")
        if isinstance(error_payload, Mapping):
            error_code = str(error_payload.get("code", "provider_error"))
            message = str(error_payload.get("message", "OpenAI Batch request failed"))
            provider_metadata["error_code"] = error_code
            return self.build_raw_error(
                request_id,
                message,
                status=ExecutionStatus.FAILED,
                job_id=str(batch.get("id", "")) or None,
                result_id=str(line.get("id", "")) or None,
                error_type=error_code,
                payload={"error": dict(error_payload)},
                provider_metadata=provider_metadata,
                metadata=metadata,
            )

        response = line.get("response")
        if isinstance(response, Mapping):
            status_code = int(response.get("status_code", 0) or 0)
            if status_code < 400:
                return None
            provider_metadata["status_code"] = status_code
            provider_metadata["openai_request_id"] = response.get("request_id")
            response_body = response.get("body", {})
            if not isinstance(response_body, Mapping):
                response_body = {"body": response_body}
            error_object = response_body.get("error", {})
            message = f"OpenAI request failed with status {status_code}"
            error_type = f"http_{status_code}"
            if isinstance(error_object, Mapping):
                message = str(error_object.get("message", message))
                error_type = str(error_object.get("type") or error_object.get("code") or error_type)
            return self.build_raw_error(
                request_id,
                message,
                status=ExecutionStatus.FAILED,
                job_id=str(batch.get("id", "")) or None,
                result_id=str(line.get("id", "")) or None,
                error_type=error_type,
                payload={"response": dict(response_body)},
                provider_metadata=provider_metadata,
                metadata=metadata,
            )
        return None

    def _result_metadata_from_context(self, context: Mapping[str, Any]) -> dict[str, Any]:
        metadata = dict(context.get("metadata", {})) if isinstance(context.get("metadata"), Mapping) else {}
        group_id = context.get("group_id")
        if group_id is not None and "group_id" not in metadata:
            metadata["group_id"] = group_id
        row_id_column = context.get("row_id_column")
        if row_id_column is not None and "row_id_column" not in metadata:
            metadata["row_id_column"] = str(row_id_column)
        row_ids = context.get("row_ids")
        if isinstance(row_ids, Sequence) and not isinstance(row_ids, (str, bytes, bytearray)):
            metadata.setdefault("row_ids", [str(row_id) for row_id in row_ids])
        unit_ids = context.get("unit_ids")
        if isinstance(unit_ids, Sequence) and not isinstance(unit_ids, (str, bytes, bytearray)):
            metadata.setdefault("unit_ids", [str(unit_id) for unit_id in unit_ids])
        return metadata

    def _handle_provider_metadata(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        request_counts = batch.get("request_counts", {})
        return {
            "batch": dict(batch),
            "endpoint": batch.get("endpoint"),
            "input_file_id": batch.get("input_file_id"),
            "output_file_id": batch.get("output_file_id"),
            "error_file_id": batch.get("error_file_id"),
            "request_counts": dict(request_counts) if isinstance(request_counts, Mapping) else {},
        }

    def _normalize_batch_status(self, batch: Mapping[str, Any]) -> ExecutionStatus:
        status = str(batch.get("status", "")).strip()
        request_counts = batch.get("request_counts", {})
        completed = 0
        failed = 0
        if isinstance(request_counts, Mapping):
            completed = int(request_counts.get("completed", 0) or 0)
            failed = int(request_counts.get("failed", 0) or 0)

        if status == "validating":
            return ExecutionStatus.SUBMITTED
        if status in {"in_progress", "finalizing", "cancelling"}:
            return ExecutionStatus.RUNNING
        if status == "completed":
            if completed > 0 and failed > 0:
                return ExecutionStatus.PARTIAL
            if completed == 0 and failed > 0:
                return ExecutionStatus.FAILED
            return ExecutionStatus.SUCCEEDED
        if status == "expired":
            return ExecutionStatus.PARTIAL if completed > 0 else ExecutionStatus.FAILED
        if status == "cancelled":
            return ExecutionStatus.PARTIAL if completed > 0 else ExecutionStatus.CANCELLED
        if status == "failed":
            return ExecutionStatus.FAILED
        msg = f"unsupported OpenAI batch status: {status!r}"
        raise OpenAIBatchProviderError(msg)

    def _request_total(self, batch: Mapping[str, Any], *, default: int | None = None) -> int | None:
        request_counts = batch.get("request_counts", {})
        if not isinstance(request_counts, Mapping):
            return default
        total = request_counts.get("total")
        if total is None:
            return default
        return int(total)

    def _timestamp_from_batch(self, batch: Mapping[str, Any], field_name: str) -> datetime | None:
        timestamp = batch.get(field_name)
        if timestamp is None:
            return None
        return datetime.fromtimestamp(int(timestamp), tz=UTC)

    def _completed_timestamp_from_batch(self, batch: Mapping[str, Any]) -> datetime | None:
        for field_name in ("completed_at", "failed_at", "expired_at", "cancelled_at"):
            timestamp = self._timestamp_from_batch(batch, field_name)
            if timestamp is not None:
                return timestamp
        return None

    def _extract_response_content(self, response_body: Mapping[str, Any]) -> str | None:
        if "output_text" in response_body and isinstance(response_body["output_text"], str):
            return response_body["output_text"]

        choices = response_body.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, Mapping):
                message = first_choice.get("message", {})
                if isinstance(message, Mapping):
                    content = message.get("content")
                    rendered = self._coerce_content_to_text(content)
                    if rendered is not None:
                        return rendered

        output_items = response_body.get("output")
        rendered = self._coerce_content_to_text(output_items)
        if rendered is not None:
            return rendered
        return None

    def _coerce_content_to_text(self, content: Any) -> str | None:
        if isinstance(content, str):
            return content

        if isinstance(content, Mapping):
            for key in ("output_text", "content", "text"):
                value = content.get(key)
                rendered = self._coerce_content_to_text(value)
                if rendered is not None:
                    return rendered
            return None

        if not isinstance(content, Sequence) or isinstance(content, (str, bytes, bytearray)):
            return None

        parts: list[str] = []
        for item in content:
            rendered = self._coerce_content_to_text(item)
            if rendered is not None:
                parts.append(rendered)
        if not parts:
            return None
        return "\n".join(parts)

    def _decode_json_response(self, status_code: int, response_body: bytes) -> Mapping[str, Any]:
        if status_code >= 400:
            self._raise_api_error(status_code, response_body)
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            msg = "OpenAI API returned a non-JSON response"
            raise OpenAIBatchProviderError(msg) from exc
        if not isinstance(decoded, Mapping):
            msg = "OpenAI API returned a non-object JSON response"
            raise OpenAIBatchProviderError(msg)
        return dict(decoded)

    def _raise_api_error(self, status_code: int, response_body: bytes) -> None:
        message = f"OpenAI API request failed with status {status_code}"
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = response_body.decode("utf-8", errors="replace").strip()
            if text:
                message = f"{message}: {text}"
            raise OpenAIBatchProviderError(message)

        if isinstance(decoded, Mapping):
            error_payload = decoded.get("error", decoded)
            if isinstance(error_payload, Mapping):
                error_message = error_payload.get("message")
                if error_message:
                    message = f"{message}: {error_message}"
        raise OpenAIBatchProviderError(message)

    def _urllib_request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = urllib_request.Request(url=url, data=body, method=method.upper())
        for header_name, header_value in headers.items():
            request.add_header(header_name, header_value)
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib_error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()


__all__ = [
    "OpenAIBatchProvider",
    "OpenAIBatchProviderError",
]
