# Config Reference

`RunConfig` is the root JSON object for the CLI and orchestrator. The easiest way to start is to copy one of the files in `examples/config/`.

## Top-level shape

```json
{
  "run_metadata": {},
  "source_input": {},
  "task_kind": "single",
  "task": {},
  "builder": {},
  "parser": {},
  "provider": {},
  "artifact_store": {},
  "grouping": null,
  "prompt_assets": {},
  "output": {},
  "retry_policy": {}
}
```

## Component references

Tasks, builders, parsers, providers, and artifact stores are serialized as importable component references:

```json
{
  "import_path": "llm_batch_annotate.SimpleTemplateBuilder",
  "settings": {
    "required_unit_fields": ["query"]
  }
}
```

`settings` are passed as keyword arguments when the component is instantiated.

## Important sections

### `run_metadata`

- `run_name`: human-readable name for the run.
- `description`: optional description.
- `tags`: optional list of tags.
- `metadata`: arbitrary JSON metadata.

### `source_input`

- `path`: CSV, TSV, or JSONL input path.
- `format`: `csv`, `tsv`, or `jsonl`.
- `unit_id_column`: optional explicit unit id column.

### `task_kind`

- `single`: one request per unit.
- `grouped`: multiple units per request and requires a `grouping` section.

### `grouping`

For grouped runs, the built-in implementation supports:

```json
{
  "strategy": "fixed_size",
  "group_size": 3,
  "exact_coverage": true
}
```

### `prompt_assets`

- `asset_root`: optional base directory for prompt assets.
- `system_prompt_path`: system prompt text file.
- `user_prompt_template_path`: user prompt template file.
- `few_shot_examples_path`: optional asset file.
- `response_schema_path`: structured-output schema JSON file.

### `provider`

The bundled provider config is `openai_batch`:

```json
{
  "component": {
    "import_path": "llm_batch_annotate.OpenAIBatchProvider"
  },
  "config": {
    "provider_kind": "openai_batch",
    "model": "gpt-5-mini",
    "completion_window": "24h",
    "request_options": {
      "endpoint": "/v1/responses",
      "api_key_env_var": "OPEN_AI_KEY",
      "timeout_seconds": 10
    }
  }
}
```

### `artifact_store`

The bundled artifact store is local filesystem storage:

```json
{
  "component": {
    "import_path": "llm_batch_annotate.LocalArtifactStore"
  },
  "config": {
    "kind": "local",
    "root_dir": "../runs"
  }
}
```

### `retry_policy`

The model already has retry configuration fields, but the retry/repair workflow is not yet implemented as a complete user-facing feature. Keep it disabled unless you are extending the framework yourself.
