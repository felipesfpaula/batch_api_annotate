"""Pydantic configuration models for serialized workflow runs."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .._model import FrameworkModel
from ..contracts.records import ComponentRef
from ..enums import ArtifactStoreKind, GroupingStrategy, ProviderKind, SourceFormat, TaskKind


class RunMetadataConfig(FrameworkModel):
    """Human-readable metadata attached to a run."""

    run_name: str = Field(min_length=1)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceInputConfig(FrameworkModel):
    """Source dataset location and basic loading settings."""

    path: str = Field(min_length=1)
    format: SourceFormat
    row_id_column: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class GroupingConfig(FrameworkModel):
    """Configuration for grouped request planning."""

    strategy: GroupingStrategy = GroupingStrategy.FIXED_SIZE
    group_size: int = Field(ge=1)
    exact_coverage: bool = True
    max_groups: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptAssetsConfig(FrameworkModel):
    """Paths to prompt, template, and schema assets used by builders."""

    asset_root: str | None = None
    system_prompt_path: str | None = None
    user_prompt_template_path: str | None = None
    few_shot_examples_path: str | None = None
    response_schema_path: str | None = None
    assets: dict[str, str] = Field(default_factory=dict)


class OutputConfig(FrameworkModel):
    """Controls which derived artifacts are written for a run."""

    preserve_raw_outputs: bool = True
    write_manifest: bool = True
    write_summary: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetryPolicyConfig(FrameworkModel):
    """Placeholder retry settings carried in the serialized run config."""

    enabled: bool = False
    max_attempts: int = Field(default=1, ge=1)
    retry_failed_requests: bool = False
    retry_failed_items: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseProviderConfig(FrameworkModel):
    """Base class for provider-specific execution settings."""

    provider_kind: ProviderKind


class GenericProviderConfig(BaseProviderConfig):
    """Provider config for custom adapters defined outside the package."""

    provider_kind: Literal[ProviderKind.CUSTOM] = ProviderKind.CUSTOM
    settings: dict[str, Any] = Field(default_factory=dict)


class OpenAIBatchConfig(BaseProviderConfig):
    """Serializable settings for the bundled OpenAI Batch adapter."""

    provider_kind: Literal[ProviderKind.OPENAI_BATCH] = ProviderKind.OPENAI_BATCH
    model: str = Field(min_length=1)
    api_base: str | None = None
    completion_window: str = Field(default="24h", min_length=2)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_completion_window(self) -> "OpenAIBatchConfig":
        digits = self.completion_window[:-1]
        suffix = self.completion_window[-1]
        if not digits.isdigit() or suffix not in {"s", "m", "h", "d"}:
            msg = "completion_window must look like '24h' or '30m'"
            raise ValueError(msg)
        return self


ProviderConfig = Annotated[
    GenericProviderConfig | OpenAIBatchConfig,
    Field(discriminator="provider_kind"),
]


class ProviderSelectionConfig(FrameworkModel):
    """Pairs a provider component reference with its runtime config."""

    component: ComponentRef
    config: ProviderConfig


class ArtifactStoreConfig(FrameworkModel):
    """Serializable settings for artifact storage backends."""

    kind: ArtifactStoreKind = ArtifactStoreKind.LOCAL
    root_dir: str = Field(default="runs", min_length=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class ArtifactStoreSelectionConfig(FrameworkModel):
    """Pairs an artifact store component reference with its config."""

    component: ComponentRef
    config: ArtifactStoreConfig = Field(default_factory=ArtifactStoreConfig)


class RunConfig(FrameworkModel):
    """Root configuration model used by the CLI and orchestrator."""

    schema_version: str = "0.1.1"
    run_metadata: RunMetadataConfig
    source_input: SourceInputConfig
    task_kind: TaskKind
    task: ComponentRef
    builder: ComponentRef
    parser: ComponentRef
    provider: ProviderSelectionConfig
    artifact_store: ArtifactStoreSelectionConfig
    grouping: GroupingConfig | None = None
    prompt_assets: PromptAssetsConfig = Field(default_factory=PromptAssetsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)

    @model_validator(mode="after")
    def validate_task_shape(self) -> "RunConfig":
        if self.task_kind is TaskKind.GROUPED and self.grouping is None:
            msg = "grouped tasks require a grouping configuration"
            raise ValueError(msg)
        if self.task_kind is TaskKind.SINGLE and self.grouping is not None:
            msg = "single tasks must not define grouping configuration"
            raise ValueError(msg)
        return self
