# Examples

The public examples live under [`examples/`](../examples/). These files are meant to stay in version control:

- `examples/data/mock_data.csv`
- `examples/prompts/`
- `examples/templates/`
- `examples/schemas/`
- `examples/config/`

Generated run outputs go under `examples/runs/` and are ignored by Git.

## Single example

[`examples/config/run_config.json`](../examples/config/run_config.json) demonstrates:

- `SingleTaskBase`
- `SimpleTemplateBuilder`
- `StructuredOutputParser`
- `OpenAIBatchProvider`
- `LocalArtifactStore`

Each request covers one input row. The bundled schema returns a bare object, and `StructuredOutputParser` can infer the single row id from request context when it is omitted. The bundled CSV uses `query_id` as that row-id column.

In the resulting `parsed/responses.jsonl`, each single-item row contains `query_id`, `request_id`, `fields`, and `metadata`. It does not include `group_id`.

## Grouped example

[`examples/config/run_config_2.json`](../examples/config/run_config_2.json) demonstrates:

- `GroupedTaskBase`
- fixed-size groups with `group_size: 3`
- a schema that accepts up to 3 returned items

With the bundled 10-row CSV, the grouped example produces 4 requests.

In grouped runs, `parsed/responses.jsonl` keeps `query_id` at top level for each row and also includes `group_id`, so you can trace both the original row and the batch grouping.

## Artifact layout

Each run uses the canonical layout below:

```text
runs/{run_id}/
  config/run_config.json
  metadata/manifest.json
  metadata/summary.json
  tables/units.jsonl
  tables/groups.jsonl
  tables/requests.jsonl
  raw/raw_outputs.jsonl
  raw/raw_errors.jsonl
  parsed/parsed_requests.jsonl
  parsed/responses.jsonl
  parsed/failures.jsonl
```

## What to inspect first

If a run does not behave as expected, check files in this order:

1. `metadata/manifest.json`
2. `metadata/summary.json`
3. `raw/raw_outputs.jsonl`
4. `raw/raw_errors.jsonl`
5. `parsed/failures.jsonl`
6. `parsed/responses.jsonl`
