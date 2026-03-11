from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from llm_batch_annotate import (
    BaseBuilder,
    GroupRecord,
    ProgrammaticBuilderBase,
    PromptAssetsConfig,
    SimpleTemplateBuilder,
    TaskKind,
    UnitRecord,
    load_prompt_assets,
    materialize_units,
    resolve_prompt_asset_path,
)
from llm_batch_annotate.configs import (
    ArtifactStoreSelectionConfig,
    OpenAIBatchConfig,
    ProviderSelectionConfig,
    RunConfig,
)


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def make_run_config(
    prompt_assets: PromptAssetsConfig | None = None,
    *,
    task_kind: TaskKind = TaskKind.SINGLE,
) -> RunConfig:
    payload: dict[str, object] = {
        "run_metadata": {"run_name": "builder-phase"},
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
        "prompt_assets": (prompt_assets or PromptAssetsConfig()).model_dump(mode="python"),
    }
    if task_kind is TaskKind.GROUPED:
        payload["grouping"] = {"strategy": "fixed_size", "group_size": 2}
    return RunConfig.model_validate(payload)


class EchoBuilder(BaseBuilder):
    def build_render_context(
        self,
        units,
        group,
        config,
    ) -> Mapping[str, Any]:
        del group
        return self.build_base_render_context(units, None, config)

    def build_system_content(self, render_context, config) -> str | None:
        del config
        return render_context["prompt_assets"].system_prompt

    def build_user_content(self, render_context, config) -> str:
        del config
        return render_context["query"]


class CountingProgrammaticBuilder(ProgrammaticBuilderBase):
    def render_user_message(self, render_context, config) -> str:
        del config
        return f"{render_context['unit_count']} unit(s): {render_context['unit_ids_csv']}"


def make_units() -> list[UnitRecord]:
    return materialize_units(
        [
            {"unit_id": "u-1", "query": "red shoes", "source": "catalog"},
            {"unit_id": "u-2", "query": "black boots", "source": "catalog"},
        ],
        unit_id_column="unit_id",
        metadata_columns=["source"],
    )


def write_prompt_assets(tmp_path: Path) -> PromptAssetsConfig:
    (tmp_path / "system.txt").write_text("You are a helpful judge.", encoding="utf-8")
    (tmp_path / "user.txt").write_text("Label query: {query}", encoding="utf-8")
    (tmp_path / "few-shot.txt").write_text("Example: good -> relevant", encoding="utf-8")
    (tmp_path / "schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (tmp_path / "extra.md").write_text("additional context", encoding="utf-8")

    return PromptAssetsConfig(
        asset_root=str(tmp_path),
        system_prompt_path="system.txt",
        user_prompt_template_path="user.txt",
        few_shot_examples_path="few-shot.txt",
        response_schema_path="schema.json",
        assets={"extra": "extra.md"},
    )


def test_prompt_asset_loader_reads_assets_from_asset_root(tmp_path: Path) -> None:
    prompt_assets = write_prompt_assets(tmp_path)

    bundle = load_prompt_assets(prompt_assets)

    assert resolve_prompt_asset_path(prompt_assets, "system.txt") == tmp_path / "system.txt"
    assert bundle.system_prompt == "You are a helpful judge."
    assert bundle.user_prompt_template == "Label query: {query}"
    assert bundle.few_shot_examples == "Example: good -> relevant"
    assert bundle.response_schema == '{"type":"object"}'
    assert bundle.extras == {"extra": "additional context"}


def test_base_builder_validates_required_fields_and_builds_payload(tmp_path: Path) -> None:
    prompt_assets = write_prompt_assets(tmp_path)
    config = make_run_config(prompt_assets)
    builder = EchoBuilder(required_unit_fields=["query"])

    payload = builder.build_request_payload(make_units()[:1], None, config)

    assert payload["messages"] == [
        {"role": "system", "content": "You are a helpful judge."},
        {"role": "user", "content": "red shoes"},
    ]
    assert payload["metadata"]["unit_ids"] == ["u-1"]


def test_simple_template_builder_renders_from_asset_templates(tmp_path: Path) -> None:
    prompt_assets = write_prompt_assets(tmp_path)
    config = make_run_config(prompt_assets)
    builder = SimpleTemplateBuilder()

    payload = builder.build_request_payload(make_units()[:1], None, config)

    assert payload["messages"][0]["content"] == "You are a helpful judge."
    assert payload["messages"][1]["content"] == "Example: good -> relevant\n\nLabel query: red shoes"


def test_simple_template_builder_supports_grouped_templates() -> None:
    config = make_run_config(task_kind=TaskKind.GROUPED)
    builder = SimpleTemplateBuilder(
        system_template="Group {group[group_id]}",
        user_template="Annotate {unit_count} units: {unit_ids_csv}\n{units_json}",
    )
    units = make_units()
    group = GroupRecord(group_id="group-000001", unit_ids=["u-1", "u-2"], group_index=1)

    payload = builder.build_request_payload(units, group, config)

    assert payload["messages"][0]["content"] == "Group group-000001"
    assert "Annotate 2 units: u-1,u-2" in payload["messages"][1]["content"]
    assert payload["metadata"]["group_id"] == "group-000001"


def test_simple_template_builder_rejects_missing_template_variables() -> None:
    config = make_run_config()
    builder = SimpleTemplateBuilder(user_template="Missing {unknown_key}")

    with pytest.raises(ValueError, match="missing template variable"):
        builder.build_request_payload(make_units()[:1], None, config)


def test_programmatic_builder_base_uses_standardized_context(tmp_path: Path) -> None:
    prompt_assets = write_prompt_assets(tmp_path)
    config = make_run_config(prompt_assets, task_kind=TaskKind.GROUPED)
    units = make_units()
    group = GroupRecord(group_id="group-000010", unit_ids=["u-1", "u-2"], group_index=10)
    builder = CountingProgrammaticBuilder()

    payload = builder.build_request_payload(units, group, config)

    assert payload["messages"][0]["content"] == "You are a helpful judge."
    assert payload["messages"][1]["content"] == "2 unit(s): u-1,u-2"
