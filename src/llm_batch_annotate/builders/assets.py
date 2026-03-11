from __future__ import annotations

from pathlib import Path

from pydantic import Field

from .._model import FrameworkModel
from ..configs.models import PromptAssetsConfig


class PromptAssetBundle(FrameworkModel):
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    few_shot_examples: str | None = None
    response_schema: str | None = None
    extras: dict[str, str] = Field(default_factory=dict)


def resolve_prompt_asset_path(prompt_assets: PromptAssetsConfig, asset_path: str | None) -> Path | None:
    if asset_path is None:
        return None

    path = Path(asset_path)
    if path.is_absolute():
        return path
    if prompt_assets.asset_root is None:
        return path
    return Path(prompt_assets.asset_root) / path


def load_prompt_asset_text(prompt_assets: PromptAssetsConfig, asset_path: str | None) -> str | None:
    resolved_path = resolve_prompt_asset_path(prompt_assets, asset_path)
    if resolved_path is None:
        return None
    return resolved_path.read_text(encoding="utf-8")


def load_prompt_assets(prompt_assets: PromptAssetsConfig) -> PromptAssetBundle:
    return PromptAssetBundle(
        system_prompt=load_prompt_asset_text(prompt_assets, prompt_assets.system_prompt_path),
        user_prompt_template=load_prompt_asset_text(prompt_assets, prompt_assets.user_prompt_template_path),
        few_shot_examples=load_prompt_asset_text(prompt_assets, prompt_assets.few_shot_examples_path),
        response_schema=load_prompt_asset_text(prompt_assets, prompt_assets.response_schema_path),
        extras={
            asset_name: load_prompt_asset_text(prompt_assets, asset_path) or ""
            for asset_name, asset_path in prompt_assets.assets.items()
        },
    )
