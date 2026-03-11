from __future__ import annotations

from llm_batch_annotate import ArtifactKind, ExecutionStatus, FailureKind, ProviderKind, RunStatus, TaskKind


def test_enum_values_are_stable() -> None:
    assert TaskKind.SINGLE.value == "single"
    assert TaskKind.GROUPED.value == "grouped"
    assert RunStatus.PENDING.value == "pending"
    assert ProviderKind.OPENAI_BATCH.value == "openai_batch"
    assert ArtifactKind.FLATTENED_ANNOTATIONS.value == "flattened_annotations"
    assert ExecutionStatus.SUBMITTED.value == "submitted"
    assert FailureKind.PARSE.value == "parse"


def test_artifact_kind_values_are_unique() -> None:
    values = [artifact_kind.value for artifact_kind in ArtifactKind]
    assert len(values) == len(set(values))
