from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..contracts.records import ArtifactRef
from ..enums import ArtifactFormat, ArtifactKind


@dataclass(frozen=True)
class ArtifactDefinition:
    artifact_kind: ArtifactKind
    format: ArtifactFormat
    relative_path: PurePosixPath


ARTIFACT_REGISTRY: dict[ArtifactKind, ArtifactDefinition] = {
    ArtifactKind.RUN_CONFIG: ArtifactDefinition(
        artifact_kind=ArtifactKind.RUN_CONFIG,
        format=ArtifactFormat.JSON,
        relative_path=PurePosixPath("config/run_config.json"),
    ),
    ArtifactKind.MANIFEST: ArtifactDefinition(
        artifact_kind=ArtifactKind.MANIFEST,
        format=ArtifactFormat.JSON,
        relative_path=PurePosixPath("metadata/manifest.json"),
    ),
    ArtifactKind.SUMMARY: ArtifactDefinition(
        artifact_kind=ArtifactKind.SUMMARY,
        format=ArtifactFormat.JSON,
        relative_path=PurePosixPath("metadata/summary.json"),
    ),
    ArtifactKind.UNITS: ArtifactDefinition(
        artifact_kind=ArtifactKind.UNITS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("tables/units.jsonl"),
    ),
    ArtifactKind.GROUPS: ArtifactDefinition(
        artifact_kind=ArtifactKind.GROUPS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("tables/groups.jsonl"),
    ),
    ArtifactKind.REQUESTS: ArtifactDefinition(
        artifact_kind=ArtifactKind.REQUESTS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("tables/requests.jsonl"),
    ),
    ArtifactKind.RAW_OUTPUTS: ArtifactDefinition(
        artifact_kind=ArtifactKind.RAW_OUTPUTS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("raw/raw_outputs.jsonl"),
    ),
    ArtifactKind.RAW_ERRORS: ArtifactDefinition(
        artifact_kind=ArtifactKind.RAW_ERRORS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("raw/raw_errors.jsonl"),
    ),
    ArtifactKind.PARSED_REQUESTS: ArtifactDefinition(
        artifact_kind=ArtifactKind.PARSED_REQUESTS,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("parsed/parsed_requests.jsonl"),
    ),
    ArtifactKind.RESPONSES: ArtifactDefinition(
        artifact_kind=ArtifactKind.RESPONSES,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("parsed/responses.jsonl"),
    ),
    ArtifactKind.FAILURES: ArtifactDefinition(
        artifact_kind=ArtifactKind.FAILURES,
        format=ArtifactFormat.JSONL,
        relative_path=PurePosixPath("parsed/failures.jsonl"),
    ),
}


def get_artifact_definition(artifact_kind: ArtifactKind) -> ArtifactDefinition:
    return ARTIFACT_REGISTRY[artifact_kind]


def run_directory(run_id: str, runs_root: str | Path = "runs") -> Path:
    return Path(runs_root) / run_id


def artifact_relative_path(artifact_kind: ArtifactKind) -> PurePosixPath:
    return get_artifact_definition(artifact_kind).relative_path


def artifact_path(run_id: str, artifact_kind: ArtifactKind, runs_root: str | Path = "runs") -> Path:
    return run_directory(run_id=run_id, runs_root=runs_root) / artifact_relative_path(artifact_kind)


def artifact_ref(artifact_kind: ArtifactKind) -> ArtifactRef:
    definition = get_artifact_definition(artifact_kind)
    return ArtifactRef(
        artifact_kind=definition.artifact_kind,
        format=definition.format,
        relative_path=str(definition.relative_path),
    )


def artifact_refs_for_run(run_id: str, runs_root: str | Path = "runs") -> dict[ArtifactKind, ArtifactRef]:
    _ = run_directory(run_id=run_id, runs_root=runs_root)
    return {artifact_kind: artifact_ref(artifact_kind) for artifact_kind in ARTIFACT_REGISTRY}
