from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import RunConfig
from ..contracts.records import GroupRecord, UnitRecord
from .assets import PromptAssetBundle
from .base import BaseBuilder


class ProgrammaticBuilderBase(BaseBuilder, ABC):
    def build_render_context(
        self,
        units: Sequence[UnitRecord],
        group: GroupRecord | None,
        config: RunConfig,
    ) -> Mapping[str, Any]:
        return self.build_base_render_context(units, group, config)

    def prompt_assets_from_context(self, render_context: Mapping[str, Any]) -> PromptAssetBundle:
        prompt_assets = render_context["prompt_assets"]
        if not isinstance(prompt_assets, PromptAssetBundle):
            msg = "render_context['prompt_assets'] must contain a PromptAssetBundle"
            raise TypeError(msg)
        return prompt_assets

    def build_system_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        return self.render_system_message(render_context, config)

    def build_user_content(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        return self.render_user_message(render_context, config)

    def render_system_message(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        del config
        return self.prompt_assets_from_context(render_context).system_prompt

    @abstractmethod
    def render_user_message(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        """Build the user message with programmatic formatting."""
