from __future__ import annotations

import json
from collections.abc import Sequence

from llm_batch_annotate import (
    GroupedTaskBase,
    OfflineTaskPipeline,
    RawErrorRecord,
    RawOutputRecord,
    SimpleTemplateBuilder,
    SingleTaskBase,
    StructuredOutputParser,
    TaskKind,
)
from llm_batch_annotate.configs import (
    ArtifactStoreSelectionConfig,
    GroupingConfig,
    OpenAIBatchConfig,
    ProviderSelectionConfig,
    RunConfig,
)
from llm_batch_annotate.contracts.records import RequestRecord


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def make_run_config(*, task_kind: TaskKind = TaskKind.SINGLE) -> RunConfig:
    payload: dict[str, object] = {
        "run_metadata": {"run_name": "task-phase"},
        "source_input": {"path": "data/input.csv", "format": "csv", "row_id_column": "query_id"},
        "task_kind": task_kind,
        "task": make_component("sample.tasks.BasicTask"),
        "builder": make_component("sample.builders.BasicBuilder"),
        "parser": make_component("sample.parsers.BasicParser"),
        "provider": ProviderSelectionConfig(
            component=make_component("sample.providers.OpenAIBatchProvider"),
            config=OpenAIBatchConfig(model="gpt-4.1-mini"),
        ),
        "artifact_store": ArtifactStoreSelectionConfig(
            component=make_component("sample.artifacts.LocalArtifactStore"),
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


def fake_executor(requests: Sequence[RequestRecord]) -> tuple[list[RawOutputRecord], list[RawErrorRecord]]:
    outputs: list[RawOutputRecord] = []
    for request in requests:
        outputs.append(
            RawOutputRecord(
                request_id=request.request_id,
                payload={
                    "content": json.dumps(
                        {
                            "items": [
                                {"query_id": unit_id, "label": f"label-{unit_id}"}
                                for unit_id in request.unit_ids
                            ]
                        }
                    )
                },
            )
        )
    return outputs, []


def fake_single_bare_executor(requests: Sequence[RequestRecord]) -> tuple[list[RawOutputRecord], list[RawErrorRecord]]:
    outputs: list[RawOutputRecord] = []
    for request in requests:
        unit_id = request.unit_ids[0]
        outputs.append(
            RawOutputRecord(
                request_id=request.request_id,
                payload={"content": json.dumps({"label": f"label-{unit_id}"})},
            )
        )
    return outputs, []


def test_single_task_base_creates_single_unit_groups_and_requests() -> None:
    task = SingleTaskBase(required_input_columns=["query"], unit_field_columns=["query"])
    builder = SimpleTemplateBuilder(user_template="Annotate {query}")
    config = make_run_config()

    units = task.materialize_units(sample_rows()[:2], config)
    groups = task.plan_groups(units, config)
    requests = task.build_requests(units, groups, builder, config)

    assert [group.unit_ids for group in groups] == [["q-1"], ["q-2"]]
    assert [request.request_id for request in requests] == ["q-1", "q-2"]
    assert requests[0].payload["messages"][0]["content"] == "Annotate red shoes"


def test_grouped_task_base_creates_fixed_size_groups_and_grouped_requests() -> None:
    task = GroupedTaskBase(required_input_columns=["query"], unit_field_columns=["query"])
    builder = SimpleTemplateBuilder(user_template="Annotate {row_ids_csv}")
    config = make_run_config(task_kind=TaskKind.GROUPED)

    units = task.materialize_units(sample_rows(), config)
    groups = task.plan_groups(units, config)
    requests = task.build_requests(units, groups, builder, config)

    assert [group.unit_ids for group in groups] == [["q-1", "q-2"], ["q-3"]]
    assert requests[0].group_id == "group-000000"
    assert requests[0].payload["messages"][0]["content"] == "Annotate q-1,q-2"


def test_offline_pipeline_runs_single_task_end_to_end() -> None:
    pipeline = OfflineTaskPipeline(
        task=SingleTaskBase(required_input_columns=["query"], unit_field_columns=["query"]),
        builder=SimpleTemplateBuilder(user_template="Annotate {query}"),
        parser=StructuredOutputParser(),
        config=make_run_config(),
    )

    result = pipeline.run(sample_rows()[:2], fake_executor)

    assert len(result.units) == 2
    assert len(result.groups) == 2
    assert len(result.requests) == 2
    assert len(result.parsed_requests) == 2
    assert len(result.annotations) == 2
    assert result.failures == []
    assert [annotation.fields["label"] for annotation in result.annotations] == ["label-q-1", "label-q-2"]


def test_offline_pipeline_runs_single_task_end_to_end_without_unit_id_in_output() -> None:
    pipeline = OfflineTaskPipeline(
        task=SingleTaskBase(required_input_columns=["query"], unit_field_columns=["query"]),
        builder=SimpleTemplateBuilder(user_template="Annotate {query}"),
        parser=StructuredOutputParser(),
        config=make_run_config(),
    )

    result = pipeline.run(sample_rows()[:2], fake_single_bare_executor)

    assert len(result.parsed_requests) == 2
    assert len(result.annotations) == 2
    assert result.failures == []
    assert [annotation.unit_id for annotation in result.annotations] == ["q-1", "q-2"]
    assert [annotation.fields["label"] for annotation in result.annotations] == ["label-q-1", "label-q-2"]


def test_offline_pipeline_runs_grouped_task_end_to_end() -> None:
    pipeline = OfflineTaskPipeline(
        task=GroupedTaskBase(required_input_columns=["query"], unit_field_columns=["query"]),
        builder=SimpleTemplateBuilder(user_template="Annotate {row_ids_csv}"),
        parser=StructuredOutputParser(),
        config=make_run_config(task_kind=TaskKind.GROUPED),
    )

    result = pipeline.run(sample_rows(), fake_executor)

    assert len(result.groups) == 2
    assert [group.unit_ids for group in result.groups] == [["q-1", "q-2"], ["q-3"]]
    assert len(result.parsed_requests) == 2
    assert len(result.annotations) == 3
    assert result.failures == []
    assert [annotation.unit_id for annotation in result.annotations] == ["q-1", "q-2", "q-3"]
