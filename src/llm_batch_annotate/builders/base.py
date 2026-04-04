from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import PromptAssetsConfig, RunConfig
from ..contracts.base import BaseMessageBuilder
from ..contracts.records import GroupRecord, UnitRecord
from .assets import PromptAssetBundle, load_prompt_assets


class BaseBuilder(BaseMessageBuilder, ABC):
    def __init__(self, *, required_unit_fields: Sequence[str] | None = None) -> None:
        self.required_unit_fields = tuple(required_unit_fields or ())

    def _row_id_column(self, config: RunConfig) -> str:
        return config.source_input.row_id_column

    def validate_inputs(
        self,
        units: Sequence[UnitRecord],
        prompt_assets: PromptAssetsConfig,
        config: RunConfig,
    ) -> None:
        if not units:
            msg = "at least one unit is required to build a request"
            raise ValueError(msg)

        for unit in units:
            missing_fields = [field for field in self.required_unit_fields if field not in unit.fields]
            if missing_fields:
                missing_text = ", ".join(missing_fields)
                msg = f"unit '{unit.unit_id}' is missing required field(s): {missing_text}"
                raise ValueError(msg)

        assets = self.load_assets(prompt_assets)
        self.validate_prompt_assets(assets, prompt_assets, config)

    def validate_prompt_assets(
        self,
        assets: PromptAssetBundle,
        prompt_assets: PromptAssetsConfig,
        config: RunConfig,
    ) -> None:
        del assets, prompt_assets, config

    def load_assets(self, prompt_assets: PromptAssetsConfig) -> PromptAssetBundle:
        return load_prompt_assets(prompt_assets)

    def serialize_unit(self, unit: UnitRecord, config: RunConfig) -> dict[str, Any]:
        row_id_column = self._row_id_column(config)
        return {
            row_id_column: unit.unit_id,
            "source_row_index": unit.source_row_index,
            "fields": dict(unit.fields),
            "metadata": dict(unit.metadata),
        }

    def serialize_group(self, group: GroupRecord | None, config: RunConfig) -> dict[str, Any] | None:
        if group is None:
            return None
        row_ids = list(group.unit_ids)
        return {
            "group_id": group.group_id,
            "row_id_column": self._row_id_column(config),
            "row_ids": row_ids,
            "unit_ids": row_ids,
            "group_index": group.group_index,
            "metadata": dict(group.metadata),
        }

    def build_base_render_context(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> dict[str, Any]:
        assets = self.load_assets(config.prompt_assets)
        row_id_column = self._row_id_column(config)
        row_ids = [unit.unit_id for unit in units]
        serialized_units = [self.serialize_unit(unit, config) for unit in units]
        serialized_group = self.serialize_group(group, config)

        context: dict[str, Any] = {
            "run_name": config.run_metadata.run_name,
            "task_kind": config.task_kind.value,
            "row_id_column": row_id_column,
            "unit_count": len(units),
            "row_ids": row_ids,
            "row_ids_csv": ",".join(row_ids),
            "unit_ids": row_ids,
            "unit_ids_csv": ",".join(row_ids),
            "units": serialized_units,
            "units_json": json.dumps(serialized_units, sort_keys=True, default=str),
            "group": serialized_group,
            "group_json": json.dumps(serialized_group, sort_keys=True, default=str) if serialized_group else "",
            "prompt_assets": assets,
            "few_shot_examples": assets.few_shot_examples,
            "response_schema": assets.response_schema,
            "asset_extras": dict(assets.extras),
        }

        if len(units) == 1:
            unit = units[0]
            context["unit"] = serialized_units[0]
            context["row_id"] = unit.unit_id
            context["unit_id"] = unit.unit_id
            context["fields"] = dict(unit.fields)
            context["metadata"] = dict(unit.metadata)
            for field_name, field_value in unit.fields.items():
                context.setdefault(field_name, field_value)

        return context

    @abstractmethod
    def build_render_context(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        """Build a render context from units and optional group context."""

    @abstractmethod
    def build_system_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        """Build the system prompt content for a request."""

    @abstractmethod
    def build_user_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        """Build the user content for a request."""

    def build_request_payload(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        self.validate_inputs(units, config.prompt_assets, config)
        render_context = self.build_render_context(units, group, config)
        system_content = self.build_system_content(render_context, config)
        user_content = self.build_user_content(render_context, config)

        if not user_content.strip():
            msg = "user content must be non-empty"
            raise ValueError(msg)

        messages: list[dict[str, str]] = []
        if system_content is not None and system_content.strip():
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": user_content})

        payload_metadata: dict[str, Any] = {
            "run_name": config.run_metadata.run_name,
            "task_kind": config.task_kind.value,
            "row_id_column": self._row_id_column(config),
            "row_ids": [unit.unit_id for unit in units],
            "unit_ids": [unit.unit_id for unit in units],
            "unit_count": len(units),
        }
        if group is not None:
            payload_metadata["group_id"] = group.group_id
            payload_metadata["group_index"] = group.group_index

        return {
            "messages": messages,
            "metadata": payload_metadata,
        }
