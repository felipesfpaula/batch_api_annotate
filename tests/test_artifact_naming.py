from __future__ import annotations

from pathlib import Path

from llm_batch_annotate import (
    ARTIFACT_REGISTRY,
    ArtifactFormat,
    ArtifactKind,
    artifact_path,
    artifact_ref,
    artifact_relative_path,
)


EXPECTED_PATHS = {
    ArtifactKind.RUN_CONFIG: "config/run_config.json",
    ArtifactKind.MANIFEST: "metadata/manifest.json",
    ArtifactKind.SUMMARY: "metadata/summary.json",
    ArtifactKind.UNITS: "tables/units.jsonl",
    ArtifactKind.GROUPS: "tables/groups.jsonl",
    ArtifactKind.REQUESTS: "tables/requests.jsonl",
    ArtifactKind.RAW_OUTPUTS: "raw/raw_outputs.jsonl",
    ArtifactKind.RAW_ERRORS: "raw/raw_errors.jsonl",
    ArtifactKind.PARSED_REQUESTS: "parsed/parsed_requests.jsonl",
    ArtifactKind.RESPONSES: "parsed/responses.jsonl",
    ArtifactKind.FAILURES: "parsed/failures.jsonl",
}


def test_artifact_registry_matches_all_kinds() -> None:
    assert set(ARTIFACT_REGISTRY) == set(ArtifactKind)


def test_artifact_relative_paths_are_stable() -> None:
    actual = {artifact_kind: str(artifact_relative_path(artifact_kind)) for artifact_kind in ArtifactKind}
    assert actual == EXPECTED_PATHS


def test_artifact_path_builds_canonical_absolute_path() -> None:
    path = artifact_path(run_id="run-123", artifact_kind=ArtifactKind.UNITS, runs_root="runs")
    assert path == Path("runs/run-123/tables/units.jsonl")


def test_artifact_ref_preserves_relative_manifest_paths() -> None:
    ref = artifact_ref(ArtifactKind.SUMMARY)

    assert ref.relative_path == "metadata/summary.json"
    assert ref.format is ArtifactFormat.JSON
