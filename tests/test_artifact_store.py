from __future__ import annotations

from pathlib import Path

from llm_batch_annotate import (
    ArtifactKind,
    ComponentIdentitySummary,
    InputSummary,
    LocalArtifactStore,
    RunManifest,
    TaskKind,
    artifact_refs_for_run,
)
from llm_batch_annotate.configs import ArtifactStoreConfig


def make_component(import_path: str) -> dict[str, object]:
    return {"import_path": import_path}


def make_manifest(run_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        run_name="artifact-store-phase",
        task_kind=TaskKind.SINGLE,
        components=ComponentIdentitySummary(
            task=make_component("sample.tasks.BasicTask"),
            builder=make_component("sample.builders.BasicBuilder"),
            parser=make_component("sample.parsers.BasicParser"),
            provider=make_component("sample.providers.OpenAIBatchProvider"),
            artifact_store=make_component("sample.artifacts.LocalArtifactStore"),
        ),
        input_summary=InputSummary(source_path="data/input.csv", source_format="csv"),
        artifacts=artifact_refs_for_run(run_id),
    )


def test_initialize_run_creates_namespace_and_artifact_directories(tmp_path: Path) -> None:
    store = LocalArtifactStore()
    config = ArtifactStoreConfig(root_dir=str(tmp_path / "runs"))

    run_path = store.initialize_run("run-001", config)

    assert run_path == tmp_path / "runs" / "run-001"
    assert (run_path / "config").is_dir()
    assert (run_path / "metadata").is_dir()
    assert (run_path / "tables").is_dir()
    assert (run_path / "raw").is_dir()
    assert (run_path / "parsed").is_dir()


def test_write_and_read_artifact_round_trip_text(tmp_path: Path) -> None:
    store = LocalArtifactStore()
    config = ArtifactStoreConfig(root_dir=str(tmp_path / "runs"))
    store.initialize_run("run-001", config)

    ref = store.write_artifact("run-001", ArtifactKind.SUMMARY, '{"ok": true}\n', config)
    content = store.read_artifact("run-001", ArtifactKind.SUMMARY, config)

    assert ref.relative_path == "metadata/summary.json"
    assert content == '{"ok": true}\n'
    assert (tmp_path / "runs" / "run-001" / "metadata" / "summary.json").read_text(encoding="utf-8") == '{"ok": true}\n'


def test_resolve_artifact_uses_canonical_relative_paths(tmp_path: Path) -> None:
    store = LocalArtifactStore()
    config = ArtifactStoreConfig(root_dir=str(tmp_path / "runs"))

    ref = store.resolve_artifact("run-123", ArtifactKind.UNITS, config)

    assert ref.artifact_kind is ArtifactKind.UNITS
    assert ref.relative_path == "tables/units.jsonl"


def test_write_manifest_persists_manifest_json(tmp_path: Path) -> None:
    store = LocalArtifactStore()
    config = ArtifactStoreConfig(root_dir=str(tmp_path / "runs"))
    manifest = make_manifest("run-001")

    ref = store.write_manifest(manifest, config)
    manifest_path = tmp_path / "runs" / "run-001" / "metadata" / "manifest.json"
    persisted = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    assert ref.artifact_kind is ArtifactKind.MANIFEST
    assert ref.relative_path == "metadata/manifest.json"
    assert persisted.run_id == "run-001"
    assert persisted.run_name == "artifact-store-phase"
