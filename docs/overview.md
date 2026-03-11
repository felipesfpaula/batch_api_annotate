# Overview

`llm-batch-annotate` is designed for workflows where you need to annotate many rows with an LLM and keep the process auditable. A run is described by a serialized `RunConfig`, executed through an `ExecutionProvider`, and persisted as a structured run directory with manifests, raw provider outputs, parsed results, and failures.

## What the package does

- Materializes source rows into stable `UnitRecord` values.
- Supports single-item and fixed-size grouped request planning.
- Builds prompt payloads from reusable prompt assets and templates.
- Submits batch jobs through a provider adapter.
- Polls and resumes long-running runs without resubmitting finished work.
- Parses structured model outputs and validates unit coverage.
- Writes canonical run artifacts that are easy to inspect or post-process.

## Core concepts

- `RunConfig`: the serialized configuration that describes a run.
- `RunManifest`: the authoritative runtime record for a run.
- `TaskOrchestrator`: the end-to-end coordinator for prepare, submit, poll, retrieve, parse, flatten, and finalize.
- `OpenAIBatchProvider`: the first concrete execution adapter.
- `LocalArtifactStore`: the default filesystem-backed artifact store.

## Intended use cases

- Batch classification or extraction over CSV, TSV, or JSONL input files.
- Grouped prompts where a single request covers multiple rows.
- Offline, resumable processing where API jobs finish minutes or hours later.
- Reproducible experiments where prompts, schemas, requests, and outputs need to be persisted.
