from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from llm_batch_annotate import (
    ExecutionHandle,
    ExecutionProviderBase,
    ExecutionStatus,
    ProviderCapabilities,
    ProviderKind,
    RawErrorRecord,
    RawOutputRecord,
    RequestRecord,
)
from llm_batch_annotate.configs import BaseProviderConfig


class CLIFakeProvider(ExecutionProviderBase):
    _job_counter = 0
    _job_store: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        *,
        poll_statuses: Sequence[str] | None = None,
        request_behaviors: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            provider_kind=ProviderKind.CUSTOM,
            capabilities=ProviderCapabilities(provider_kind=ProviderKind.CUSTOM, max_request_count=100),
        )
        self._poll_statuses = list(poll_statuses or ["succeeded"])
        self._request_behaviors = {
            request_id: dict(behavior)
            for request_id, behavior in dict(request_behaviors or {}).items()
        }

    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: BaseProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        self.validate_request_batch(requests, config)
        type(self)._job_counter += 1
        job_id = f"job-cli-{type(self)._job_counter}"
        type(self)._job_store[job_id] = {
            "requests": list(requests),
            "poll_statuses": list(self._poll_statuses),
            "request_behaviors": dict(self._request_behaviors),
        }
        return [self.build_handle(job_id, status="submitted", request_count=len(requests))]

    def poll_status(self, handle: ExecutionHandle, config: BaseProviderConfig) -> ExecutionHandle:
        self.validate_provider_config(config)
        job = self._job_store.get(handle.job_id)
        if job is None:
            raise KeyError(f"unknown CLI fake job: {handle.job_id}")
        poll_statuses = job["poll_statuses"]
        next_status = poll_statuses.pop(0) if poll_statuses else handle.status
        request_total = len(job["requests"])
        completed = 0
        failed = 0
        if str(next_status) == "succeeded":
            completed = request_total
        elif str(next_status) == "failed":
            failed = request_total
        elif str(next_status) == "partial":
            completed = max(request_total - 1, 0)
            failed = min(request_total, 1)
        return self.update_handle(
            handle,
            status=next_status,
            provider_metadata={
                "request_counts": {
                    "completed": completed,
                    "failed": failed,
                    "total": request_total,
                }
            },
        )

    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        job = self._job_store.get(handle.job_id)
        if job is None:
            raise KeyError(f"unknown CLI fake job: {handle.job_id}")
        outputs: list[RawOutputRecord] = []
        for request in job["requests"]:
            behavior = job["request_behaviors"].get(request.request_id, {})
            if behavior.get("error"):
                continue
            items = behavior.get(
                "items",
                [{"query_id": unit_id, "label": f"label-{unit_id}"} for unit_id in request.unit_ids],
            )
            outputs.append(
                self.build_raw_output(
                    request.request_id,
                    job_id=handle.job_id,
                    payload={"content": json.dumps({"items": items})},
                )
            )
        return outputs

    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: BaseProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        job = self._job_store.get(handle.job_id)
        if job is None:
            raise KeyError(f"unknown CLI fake job: {handle.job_id}")
        errors: list[RawErrorRecord] = []
        for request in job["requests"]:
            behavior = job["request_behaviors"].get(request.request_id, {})
            message = behavior.get("error")
            if message:
                errors.append(
                    self.build_raw_error(
                        request.request_id,
                        str(message),
                        job_id=handle.job_id,
                        error_type="provider_error",
                    )
                )
        return errors


__all__ = ["CLIFakeProvider"]
