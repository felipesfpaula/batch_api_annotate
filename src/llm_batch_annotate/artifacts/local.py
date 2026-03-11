"""Filesystem-backed artifact store implementation."""

from __future__ import annotations

from pathlib import Path

from ..configs.models import ArtifactStoreConfig
from ..contracts.base import ArtifactStore
from ..contracts.records import ArtifactRef
from ..enums import ArtifactFormat, ArtifactKind, ArtifactStoreKind
from ..manifests.models import RunManifest
from .naming import ARTIFACT_REGISTRY, artifact_path, artifact_ref, run_directory


class LocalArtifactStore(ArtifactStore):
    """Persist run artifacts under a canonical local directory tree."""

    def validate_config(self, config: ArtifactStoreConfig) -> None:
        if config.kind is not ArtifactStoreKind.LOCAL:
            msg = "LocalArtifactStore requires ArtifactStoreConfig.kind='local'"
            raise ValueError(msg)

    def run_path(self, run_id: str, config: ArtifactStoreConfig) -> Path:
        self.validate_config(config)
        return run_directory(run_id=run_id, runs_root=config.root_dir)

    def artifact_path(self, run_id: str, artifact_kind: ArtifactKind, config: ArtifactStoreConfig) -> Path:
        self.validate_config(config)
        return artifact_path(run_id=run_id, artifact_kind=artifact_kind, runs_root=config.root_dir)

    def initialize_run(self, run_id: str, config: ArtifactStoreConfig) -> Path:
        run_path = self.run_path(run_id, config)
        run_path.mkdir(parents=True, exist_ok=True)

        for definition in ARTIFACT_REGISTRY.values():
            (run_path / definition.relative_path.parent).mkdir(parents=True, exist_ok=True)

        return run_path

    def write_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        content: str | bytes,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        artifact_file = self.artifact_path(run_id, artifact_kind, config)
        artifact_file.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, bytes):
            artifact_file.write_bytes(content)
        else:
            artifact_file.write_text(content, encoding="utf-8")

        return artifact_ref(artifact_kind)

    def read_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> str | bytes:
        artifact_file = self.artifact_path(run_id, artifact_kind, config)
        artifact = artifact_ref(artifact_kind)

        if artifact.format in {ArtifactFormat.JSON, ArtifactFormat.JSONL}:
            return artifact_file.read_text(encoding="utf-8")
        return artifact_file.read_bytes()

    def resolve_artifact(
        self,
        run_id: str,
        artifact_kind: ArtifactKind,
        config: ArtifactStoreConfig,
    ) -> ArtifactRef:
        _ = self.artifact_path(run_id, artifact_kind, config)
        return artifact_ref(artifact_kind)

    def write_manifest(self, manifest: RunManifest, config: ArtifactStoreConfig) -> ArtifactRef:
        self.initialize_run(manifest.run_id, config)
        return self.write_artifact(
            manifest.run_id,
            ArtifactKind.MANIFEST,
            manifest.model_dump_json(indent=2),
            config,
        )
