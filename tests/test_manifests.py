from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from llm_batch_annotate import (
    ArtifactKind,
    ComponentIdentitySummary,
    InputSummary,
    RunManifest,
    RunStatus,
    TaskKind,
    artifact_refs_for_run,
)


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def test_manifest_defaults_status_and_timestamps() -> None:
    manifest = RunManifest(
        run_id="run-001",
        run_name="phase-1",
        task_kind=TaskKind.SINGLE,
        components=ComponentIdentitySummary(
            task=make_component("sample.tasks.BasicTask"),
            builder=make_component("sample.builders.BasicBuilder"),
            parser=make_component("sample.parsers.BasicParser"),
            provider=make_component("sample.providers.OpenAIBatchProvider"),
            artifact_store=make_component("sample.artifacts.LocalArtifactStore"),
        ),
        input_summary=InputSummary(source_path="data/input.csv", source_format="csv", row_id_column="query_id"),
    )

    assert manifest.status is RunStatus.PENDING
    assert manifest.created_at.tzinfo is not None
    assert manifest.updated_at.tzinfo is not None


def test_manifest_json_round_trip_preserves_artifact_map() -> None:
    manifest = RunManifest(
        run_id="run-001",
        run_name="phase-1",
        task_kind=TaskKind.GROUPED,
        components=ComponentIdentitySummary(
            task=make_component("sample.tasks.BasicTask"),
            builder=make_component("sample.builders.BasicBuilder"),
            parser=make_component("sample.parsers.BasicParser"),
            provider=make_component("sample.providers.OpenAIBatchProvider"),
            artifact_store=make_component("sample.artifacts.LocalArtifactStore"),
        ),
        input_summary=InputSummary(
            source_path="data/input.csv",
            source_format="csv",
            source_row_count=12,
            row_id_column="query_id",
        ),
        artifacts=artifact_refs_for_run("run-001"),
    )

    encoded = manifest.model_dump_json()
    decoded = RunManifest.model_validate_json(encoded)

    assert decoded.artifacts[ArtifactKind.MANIFEST].relative_path == "metadata/manifest.json"
    assert decoded.artifacts[ArtifactKind.UNITS].relative_path == "tables/units.jsonl"


def test_manifest_rejects_artifact_key_mismatches() -> None:
    artifacts = artifact_refs_for_run("run-001")
    artifacts[ArtifactKind.MANIFEST] = artifacts[ArtifactKind.SUMMARY]

    with pytest.raises(ValidationError):
        RunManifest(
            run_id="run-001",
            run_name="phase-1",
            task_kind=TaskKind.SINGLE,
            components=ComponentIdentitySummary(
                task=make_component("sample.tasks.BasicTask"),
                builder=make_component("sample.builders.BasicBuilder"),
                parser=make_component("sample.parsers.BasicParser"),
                provider=make_component("sample.providers.OpenAIBatchProvider"),
                artifact_store=make_component("sample.artifacts.LocalArtifactStore"),
            ),
            input_summary=InputSummary(source_path="data/input.csv", source_format="csv", row_id_column="query_id"),
            artifacts=artifacts,
        )


def test_manifest_rejects_invalid_timestamp_order() -> None:
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="run-001",
            run_name="phase-1",
            task_kind=TaskKind.SINGLE,
            status=RunStatus.RUNNING,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            components=ComponentIdentitySummary(
                task=make_component("sample.tasks.BasicTask"),
                builder=make_component("sample.builders.BasicBuilder"),
                parser=make_component("sample.parsers.BasicParser"),
                provider=make_component("sample.providers.OpenAIBatchProvider"),
                artifact_store=make_component("sample.artifacts.LocalArtifactStore"),
            ),
            input_summary=InputSummary(source_path="data/input.csv", source_format="csv", row_id_column="query_id"),
        )
