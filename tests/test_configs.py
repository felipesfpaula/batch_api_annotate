from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_batch_annotate import (
    ArtifactStoreSelectionConfig,
    GroupingConfig,
    GroupingStrategy,
    OpenAIBatchConfig,
    ProviderSelectionConfig,
    RunConfig,
    TaskKind,
)


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path, "settings": {"version": "test"}}


def make_base_run_config(task_kind: TaskKind) -> dict[str, object]:
    return {
        "run_metadata": {"run_name": "phase-1-smoke"},
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


def test_single_run_config_is_valid() -> None:
    config = RunConfig.model_validate(make_base_run_config(TaskKind.SINGLE))

    assert config.task_kind is TaskKind.SINGLE
    assert config.grouping is None
    assert config.provider.config.provider_kind.value == "openai_batch"


def test_grouped_run_config_is_valid() -> None:
    payload = make_base_run_config(TaskKind.GROUPED)
    payload["grouping"] = GroupingConfig(strategy=GroupingStrategy.FIXED_SIZE, group_size=5)

    config = RunConfig.model_validate(payload)

    assert config.task_kind is TaskKind.GROUPED
    assert config.grouping is not None
    assert config.grouping.group_size == 5


def test_grouped_tasks_require_grouping_config() -> None:
    with pytest.raises(ValidationError):
        RunConfig.model_validate(make_base_run_config(TaskKind.GROUPED))


def test_single_tasks_reject_grouping_config() -> None:
    payload = make_base_run_config(TaskKind.SINGLE)
    payload["grouping"] = {"strategy": "fixed_size", "group_size": 1}

    with pytest.raises(ValidationError):
        RunConfig.model_validate(payload)


def test_component_ref_serializes_settings() -> None:
    config = RunConfig.model_validate(make_base_run_config(TaskKind.SINGLE))
    dumped = config.model_dump(mode="json")

    assert dumped["task"]["import_path"] == "sample.tasks.BasicTask"
    assert dumped["task"]["settings"] == {"version": "test"}


def test_openai_provider_config_validates_completion_window() -> None:
    with pytest.raises(ValidationError):
        OpenAIBatchConfig(model="gpt-4.1-mini", completion_window="later")
