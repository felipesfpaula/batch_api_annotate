from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from llm_batch_annotate import (
    ArtifactKind,
    ExecutionHandle,
    ExecutionProviderBase,
    ExecutionStatus,
    FailureKind,
    GroupedTaskBase,
    LocalArtifactStore,
    ProviderCapabilities,
    ProviderKind,
    RawErrorRecord,
    RawOutputRecord,
    SimpleTemplateBuilder,
    SingleTaskBase,
    StructuredOutputParser,
    TaskOrchestrator,
    TaskRunState,
)
from llm_batch_annotate.configs import (
    ArtifactStoreSelectionConfig,
    GenericProviderConfig,
    GroupingConfig,
    ProviderSelectionConfig,
    RunConfig,
)
from llm_batch_annotate.contracts.records import RequestRecord
from llm_batch_annotate.enums import TaskKind


class FakeLifecycleProvider(ExecutionProviderBase):
    def __init__(
        self,
        *,
        poll_statuses: Sequence[ExecutionStatus | str] | None = None,
        request_behaviors: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            provider_kind=ProviderKind.CUSTOM,
            capabilities=ProviderCapabilities(provider_kind=ProviderKind.CUSTOM, max_request_count=100),
        )
        self._poll_statuses = list(poll_statuses or [ExecutionStatus.SUCCEEDED])
        self._request_behaviors = {
            request_id: dict(behavior)
            for request_id, behavior in dict(request_behaviors or {}).items()
        }
        self._submitted_requests: list[RequestRecord] = []
        self.poll_count = 0

    def submit_requests(
        self,
        requests: Sequence[RequestRecord],
        config: GenericProviderConfig,
    ) -> Sequence[ExecutionHandle]:
        self.validate_request_batch(requests, config)
        self._submitted_requests = list(requests)
        return [
            self.build_handle(
                "job-1",
                status=ExecutionStatus.SUBMITTED,
                request_count=len(requests),
                provider_metadata={"submitted_request_ids": [request.request_id for request in requests]},
            )
        ]

    def poll_status(self, handle: ExecutionHandle, config: GenericProviderConfig) -> ExecutionHandle:
        self.validate_provider_config(config)
        self.poll_count += 1
        next_status = self._poll_statuses.pop(0) if self._poll_statuses else handle.status
        completed_at = None
        if next_status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.PARTIAL, ExecutionStatus.FAILED}:
            completed_at = self.build_handle("job-1").submitted_at
        return self.update_handle(
            handle,
            status=next_status,
            completed_at=completed_at,
            provider_metadata={"poll_count": self.poll_count},
        )

    def retrieve_outputs(
        self,
        handle: ExecutionHandle,
        config: GenericProviderConfig,
    ) -> Sequence[RawOutputRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        outputs: list[RawOutputRecord] = []
        for request in self._submitted_requests:
            behavior = self._request_behaviors.get(request.request_id, {})
            if behavior.get("error"):
                continue
            payload = behavior.get("payload")
            if payload is None:
                items = behavior.get(
                    "items",
                    [{"query_id": unit_id, "label": f"label-{unit_id}"} for unit_id in request.unit_ids],
                )
                payload = {"content": json.dumps({"items": items})}
            outputs.append(
                self.build_raw_output(
                    request.request_id,
                    job_id=handle.job_id,
                    payload=dict(payload),
                    metadata={"provider_phase": "retrieve_outputs"},
                )
            )
        return outputs

    def retrieve_errors(
        self,
        handle: ExecutionHandle,
        config: GenericProviderConfig,
    ) -> Sequence[RawErrorRecord]:
        self.validate_provider_config(config)
        self.ensure_handle_provider(handle)
        errors: list[RawErrorRecord] = []
        for request in self._submitted_requests:
            behavior = self._request_behaviors.get(request.request_id, {})
            error_message = behavior.get("error")
            if error_message:
                errors.append(
                    self.build_raw_error(
                        request.request_id,
                        str(error_message),
                        job_id=handle.job_id,
                        error_type="provider_error",
                    )
                )
        return errors


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def make_run_config(tmp_path: Path, *, task_kind: TaskKind = TaskKind.GROUPED) -> RunConfig:
    payload: dict[str, object] = {
        "run_metadata": {"run_name": "orchestrator-phase"},
        "source_input": {"path": "data/input.csv", "format": "csv", "row_id_column": "query_id"},
        "task_kind": task_kind,
        "task": make_component("sample.tasks.BasicTask"),
        "builder": make_component("sample.builders.SimpleTemplateBuilder"),
        "parser": make_component("sample.parsers.StructuredOutputParser"),
        "provider": ProviderSelectionConfig(
            component=make_component("sample.providers.FakeLifecycleProvider"),
            config=GenericProviderConfig(),
        ),
        "artifact_store": ArtifactStoreSelectionConfig(
            component=make_component("sample.artifacts.LocalArtifactStore"),
            config={"root_dir": str(tmp_path / "runs")},
        ),
    }
    if task_kind is TaskKind.GROUPED:
        payload["grouping"] = GroupingConfig(group_size=2).model_dump(mode="python")
    return RunConfig.model_validate(payload)


def sample_rows() -> list[dict[str, str]]:
    return [
        {"query_id": "q-1", "query": "red shoes"},
        {"query_id": "q-2", "query": "black boots"},
        {"query_id": "q-3", "query": "green sandals"},
    ]


def make_orchestrator(
    tmp_path: Path,
    *,
    provider: FakeLifecycleProvider | None = None,
    task_kind: TaskKind = TaskKind.GROUPED,
) -> TaskOrchestrator:
    task = (
        GroupedTaskBase(required_input_columns=["query"], unit_field_columns=["query"])
        if task_kind is TaskKind.GROUPED
        else SingleTaskBase(required_input_columns=["query"], unit_field_columns=["query"])
    )
    user_template = "Annotate {row_ids_csv}" if task_kind is TaskKind.GROUPED else "Annotate {query}"
    return TaskOrchestrator(
        task=task,
        builder=SimpleTemplateBuilder(user_template=user_template),
        parser=StructuredOutputParser(),
        provider=provider or FakeLifecycleProvider(poll_statuses=[ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED]),
        artifact_store=LocalArtifactStore(),
        config=make_run_config(tmp_path, task_kind=task_kind),
        run_id_factory=lambda: "run-test-001",
        sleep_fn=lambda _: None,
    )


def test_prepare_writes_initial_artifacts_and_manifest(tmp_path: Path) -> None:
    orchestrator = make_orchestrator(tmp_path)

    state = orchestrator.prepare(sample_rows())

    assert isinstance(state, TaskRunState)
    assert state.run_id == "run-test-001"
    assert len(state.units) == 3
    assert len(state.groups) == 2
    assert len(state.requests) == 2
    assert state.manifest.status.value == "running"
    assert state.manifest.input_summary.source_row_count == 3
    assert state.manifest.grouping_summary is not None
    assert state.manifest.grouping_summary.group_count == 2

    run_root = tmp_path / "runs" / "run-test-001"
    assert (run_root / "config" / "run_config.json").exists()
    assert (run_root / "tables" / "units.jsonl").exists()
    assert (run_root / "tables" / "groups.jsonl").exists()
    assert (run_root / "tables" / "requests.jsonl").exists()
    manifest = json.loads((run_root / "metadata" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-test-001"
    assert manifest["artifacts"]["requests"]["relative_path"] == "tables/requests.jsonl"


def test_orchestrator_steps_run_grouped_workflow_and_finalize_summary(tmp_path: Path) -> None:
    provider = FakeLifecycleProvider(poll_statuses=[ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED])
    orchestrator = make_orchestrator(tmp_path, provider=provider)

    state = orchestrator.prepare(sample_rows())
    orchestrator.submit(state)
    orchestrator.poll(state, until_terminal=True, max_polls=2)
    orchestrator.retrieve(state)
    orchestrator.parse(state)
    orchestrator.flatten(state)
    orchestrator.finalize(state)

    assert provider.poll_count == 2
    assert state.execution_handles[0].status is ExecutionStatus.SUCCEEDED
    assert len(state.raw_outputs) == 2
    assert len(state.parsed_requests) == 2
    assert len(state.annotations) == 3
    assert state.failures == []
    assert state.manifest.status.value == "succeeded"
    assert state.manifest.parse_summary.request_count == 2
    assert state.manifest.parse_summary.parsed_request_count == 2
    assert state.manifest.parse_summary.failure_count == 0
    assert state.manifest.validation_summary.valid is True
    assert state.manifest.provider_metadata["handles"][0]["provider_metadata"]["poll_count"] == 2

    run_root = tmp_path / "runs" / "run-test-001"
    summary = json.loads((run_root / "metadata" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "succeeded"
    assert summary["counts"]["annotations"] == 3
    response_lines = (run_root / "parsed" / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(response_lines) == 3
    persisted_response = json.loads(response_lines[0])
    assert persisted_response["query_id"] == "q-1"
    assert persisted_response["group_id"] == "group-000000"
    failures_text = (run_root / "parsed" / "failures.jsonl").read_text(encoding="utf-8")
    assert failures_text == ""


def test_orchestrator_runs_single_workflow_with_inferred_unit_id(tmp_path: Path) -> None:
    provider = FakeLifecycleProvider(
        poll_statuses=[ExecutionStatus.SUCCEEDED],
        request_behaviors={
            "q-1": {"payload": {"content": json.dumps({"label": "label-q-1"})}},
        },
    )
    orchestrator = make_orchestrator(tmp_path, provider=provider, task_kind=TaskKind.SINGLE)

    state = orchestrator.run(sample_rows()[:1], poll_until_terminal=True, max_polls=1)

    assert state.manifest.status.value == "succeeded"
    assert len(state.parsed_requests) == 1
    assert len(state.annotations) == 1
    assert state.failures == []
    assert state.annotations[0].unit_id == "q-1"
    assert state.annotations[0].fields == {"label": "label-q-1"}
    run_root = tmp_path / "runs" / "run-test-001"
    persisted_response = json.loads((run_root / "parsed" / "responses.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert persisted_response["query_id"] == "q-1"
    assert "group_id" not in persisted_response


def test_orchestrator_marks_partial_when_provider_errors_reduce_coverage(tmp_path: Path) -> None:
    provider = FakeLifecycleProvider(
        poll_statuses=[ExecutionStatus.PARTIAL],
        request_behaviors={"request-000001": {"error": "provider timeout"}},
    )
    orchestrator = make_orchestrator(tmp_path, provider=provider)

    state = orchestrator.run(sample_rows(), poll_until_terminal=True, max_polls=1)

    assert state.manifest.status.value == "partial"
    assert len(state.annotations) == 2
    assert len(state.failures) == 2
    assert state.failures[0].failure_kind is FailureKind.PROVIDER_EXECUTION
    assert state.failures[1].failure_kind is FailureKind.VALIDATION
    assert state.manifest.validation_summary.valid is False
    assert state.manifest.validation_summary.missing_unit_count == 1

    run_root = tmp_path / "runs" / "run-test-001"
    failures = [
        json.loads(line)
        for line in (run_root / "parsed" / "failures.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [failure["failure_kind"] for failure in failures] == ["provider_execution", "validation"]
    persisted_manifest = json.loads((run_root / "metadata" / "manifest.json").read_text(encoding="utf-8"))
    assert persisted_manifest["status"] == "partial"
    assert persisted_manifest["provider_metadata"]["raw_error_count"] == 1


def test_orchestrator_run_stops_cleanly_when_execution_is_still_running(tmp_path: Path) -> None:
    provider = FakeLifecycleProvider(poll_statuses=[ExecutionStatus.RUNNING])
    orchestrator = make_orchestrator(tmp_path, provider=provider)

    state = orchestrator.run(sample_rows(), poll_until_terminal=False)

    assert provider.poll_count == 1
    assert state.execution_handles[0].status is ExecutionStatus.RUNNING
    assert state.raw_outputs == []
    assert state.raw_errors == []
    assert state.parsed_requests == []
    assert state.annotations == []
    assert state.failures == []
    assert state.manifest.status.value == "running"
    assert state.manifest.validation_summary.valid is True
    assert state.manifest.validation_summary.missing_unit_count == 0

    run_root = tmp_path / "runs" / "run-test-001"
    summary = json.loads((run_root / "metadata" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "running"
    assert summary["counts"]["raw_outputs"] == 0
    assert summary["counts"]["annotations"] == 0


def test_orchestrator_resume_loads_existing_run_and_completes_it(tmp_path: Path) -> None:
    provider = FakeLifecycleProvider(poll_statuses=[ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED])
    orchestrator = make_orchestrator(tmp_path, provider=provider)

    first_state = orchestrator.run(sample_rows(), poll_until_terminal=False)
    resumed_state = orchestrator.resume("run-test-001", max_polls=1)

    assert first_state.manifest.status.value == "running"
    assert provider.poll_count == 2
    assert resumed_state.manifest.status.value == "succeeded"
    assert len(resumed_state.raw_outputs) == 2
    assert len(resumed_state.annotations) == 3

    run_root = tmp_path / "runs" / "run-test-001"
    summary = json.loads((run_root / "metadata" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "succeeded"
    assert summary["counts"]["annotations"] == 3
