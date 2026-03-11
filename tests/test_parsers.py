from __future__ import annotations

from llm_batch_annotate import (
    BaseOutputParser,
    GroupRecord,
    ParsedRequestRecord,
    RawOutputRecord,
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


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def make_run_config(*, task_kind: TaskKind = TaskKind.SINGLE) -> RunConfig:
    payload: dict[str, object] = {
        "run_metadata": {"run_name": "parser-phase"},
        "source_input": {"path": "data/input.csv", "format": "csv", "unit_id_column": "unit_id"},
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


def test_base_output_parser_flattens_structured_payload() -> None:
    parser = BaseOutputParser()
    config = make_run_config()
    raw_output = RawOutputRecord(
        request_id="request-1",
        payload={"items": [{"unit_id": "u-1", "label": "relevant", "score": 0.98}]},
    )

    parsed_request = parser.parse_output(raw_output, config, unit_ids=["u-1"])
    annotations, failures = parser.flatten_request(parsed_request, ["u-1"], config)

    assert parsed_request.parsed_payload["items"][0]["label"] == "relevant"
    assert failures == []
    assert len(annotations) == 1
    assert annotations[0].unit_id == "u-1"
    assert annotations[0].fields == {"label": "relevant", "score": 0.98}


def test_structured_output_parser_parses_json_text() -> None:
    parser = StructuredOutputParser()
    config = make_run_config()
    raw_output = RawOutputRecord(
        request_id="request-1",
        payload={"content": '{"items":[{"unit_id":"u-1","label":"relevant"}]}'},
    )

    parsed_request = parser.parse_output(raw_output, config, unit_ids=["u-1"])

    assert parsed_request.parsed_payload == {"items": [{"unit_id": "u-1", "label": "relevant"}]}


def test_grouped_flattening_uses_group_membership_and_validates_coverage() -> None:
    parser = StructuredOutputParser()
    config = make_run_config(task_kind=TaskKind.GROUPED)
    group = GroupRecord(group_id="group-1", unit_ids=["u-1", "u-2"], group_index=0)
    parsed_request = ParsedRequestRecord(
        request_id="request-1",
        group_id="group-1",
        unit_ids=["u-1", "u-2"],
        parsed_payload={
            "items": [
                {"unit_id": "u-1", "label": "relevant"},
                {"unit_id": "u-2", "label": "irrelevant"},
            ]
        },
    )

    annotations, failures = parser.flatten_grouped_requests([parsed_request], [group], config)

    assert failures == []
    assert [annotation.unit_id for annotation in annotations] == ["u-1", "u-2"]
    assert [annotation.fields["label"] for annotation in annotations] == ["relevant", "irrelevant"]


def test_parser_emits_parse_failure_records_for_invalid_json() -> None:
    parser = StructuredOutputParser()
    config = make_run_config()
    raw_output = RawOutputRecord(
        request_id="request-1",
        payload={"content": '{"items":[{"unit_id":"u-1"}'},
    )

    parsed_requests, failures = parser.parse_outputs(
        [raw_output],
        config,
        request_context={"request-1": {"unit_ids": ["u-1"]}},
    )

    assert parsed_requests == []
    assert len(failures) == 1
    assert failures[0].failure_kind.value == "parse"
    assert failures[0].request_id == "request-1"
    assert failures[0].details["exception_type"] == "ValueError"


def test_parser_emits_flatten_failure_when_unit_id_is_missing() -> None:
    parser = BaseOutputParser()
    config = make_run_config()
    parsed_request = ParsedRequestRecord(
        request_id="request-1",
        unit_ids=["u-1"],
        parsed_payload={"items": [{"label": "relevant"}]},
    )

    annotations, failures = parser.flatten_request(parsed_request, ["u-1"], config)

    assert annotations == []
    assert len(failures) == 1
    assert failures[0].failure_kind.value == "flatten"
    assert failures[0].request_id == "request-1"


def test_parser_emits_validation_failures_for_missing_group_members() -> None:
    parser = BaseOutputParser()
    config = make_run_config(task_kind=TaskKind.GROUPED)
    parsed_request = ParsedRequestRecord(
        request_id="request-1",
        group_id="group-1",
        unit_ids=["u-1", "u-2"],
        parsed_payload={"items": [{"unit_id": "u-1", "label": "relevant"}]},
    )

    annotations, failures = parser.flatten_request(parsed_request, ["u-1", "u-2"], config)

    assert len(annotations) == 1
    assert len(failures) == 1
    assert failures[0].failure_kind.value == "validation"
    assert failures[0].details["missing_unit_ids"] == ["u-2"]
