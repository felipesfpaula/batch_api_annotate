from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import PromptAssetsConfig, RunConfig
from .assets import PromptAssetBundle
from .programmatic import ProgrammaticBuilderBase


class SimpleTemplateBuilder(ProgrammaticBuilderBase):
    def __init__(
        self,
        *,
        user_template: str | None = None,
        system_template: str | None = None,
        required_unit_fields: Sequence[str] | None = None,
        prepend_few_shot_examples: bool = True,
    ) -> None:
        super().__init__(required_unit_fields=required_unit_fields)
        self.user_template = user_template
        self.system_template = system_template
        self.prepend_few_shot_examples = prepend_few_shot_examples

    def validate_prompt_assets(
        self,
        assets: PromptAssetBundle,
        prompt_assets: PromptAssetsConfig,
        config: RunConfig,
    ) -> None:
        del prompt_assets, config
        if self.user_template is None and assets.user_prompt_template is None:
            msg = "a user template must be provided inline or through prompt assets"
            raise ValueError(msg)

    def _template_context(self, render_context: Mapping[str, Any]) -> dict[str, Any]:
        prompt_assets = self.prompt_assets_from_context(render_context)
        context = dict(render_context)
        context["prompt_assets"] = prompt_assets.model_dump(mode="python")
        return context

    def _render_template(self, template: str, render_context: Mapping[str, Any]) -> str:
        context = self._template_context(render_context)
        try:
            return template.format_map(context)
        except KeyError as exc:
            missing_key = exc.args[0]
            msg = f"missing template variable '{missing_key}' in render context"
            raise ValueError(msg) from exc

    def render_system_message(self, render_context: Mapping[str, Any], config: RunConfig) -> str | None:
        del config
        prompt_assets = self.prompt_assets_from_context(render_context)
        template = self.system_template or prompt_assets.system_prompt
        if template is None:
            return None
        return self._render_template(template, render_context)

    def render_user_message(self, render_context: Mapping[str, Any], config: RunConfig) -> str:
        del config
        prompt_assets = self.prompt_assets_from_context(render_context)
        template = self.user_template or prompt_assets.user_prompt_template
        if template is None:
            msg = "a user template must be provided inline or through prompt assets"
            raise ValueError(msg)

        user_content = self._render_template(template, render_context)
        if self.prepend_few_shot_examples and prompt_assets.few_shot_examples:
            return f"{prompt_assets.few_shot_examples}\n\n{user_content}"
        return user_content
