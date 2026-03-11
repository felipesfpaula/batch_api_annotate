# Architecture

The framework is organized around a small set of stable contracts.

## Data flow

1. Source rows are loaded from CSV, TSV, or JSONL.
2. A task materializes `UnitRecord` values.
3. The task plans `GroupRecord` values.
4. A builder turns units or groups into request payloads.
5. A provider submits the requests and returns `ExecutionHandle` values.
6. The orchestrator polls the provider, then retrieves raw outputs and errors.
7. A parser converts raw outputs into structured request payloads.
8. Parsed request payloads are flattened into per-unit annotations.
9. Coverage validation ensures the final unit set matches expectations.
10. The artifact store persists every stage.

## Main modules

- `llm_batch_annotate.configs.models`: typed run configuration.
- `llm_batch_annotate.contracts.base`: base interfaces for tasks, builders, parsers, providers, and artifact stores.
- `llm_batch_annotate.execution.providers.openai_batch`: the OpenAI Batch adapter.
- `llm_batch_annotate.orchestration.run`: run lifecycle orchestration.
- `llm_batch_annotate.artifacts.local`: local filesystem artifact storage.

## Design goals

- provider-agnostic execution contracts
- explicit manifests and artifact naming
- resumable long-running jobs
- strict JSON configuration and typed records
- support for grouped inputs and exact coverage validation
