# Quickstart

The repository includes runnable example assets in [`examples/`](../examples/). Generated run artifacts are written under `examples/runs/` and are intentionally ignored by Git.

## Single-item example

The bundled single-item example uses `query_id` as the canonical row id, returns a bare JSON object, and lets the parser infer that id from the request context.

Submit the example run and poll once:

```bash
export OPEN_AI_KEY="sk-..."
PYTHONPATH=src .venv/bin/python -m llm_batch_annotate.cli run examples/config/run_config.json --run-id example-single --no-poll-until-terminal
```

Resume the same run later and wait up to 10 polls, every 2 minutes:

```bash
PYTHONPATH=src .venv/bin/python -m llm_batch_annotate.cli resume examples/config/run_config.json example-single --poll-interval 2m --max-polls 10
```

## Grouped example

The grouped example sends up to 3 units per request, so the bundled 10-row CSV becomes 4 requests with sizes `3, 3, 3, 1`.

```bash
export OPEN_AI_KEY="sk-..."
PYTHONPATH=src .venv/bin/python -m llm_batch_annotate.cli run examples/config/run_config_2.json --run-id example-grouped --no-poll-until-terminal
```

Resume and continue polling:

```bash
PYTHONPATH=src .venv/bin/python -m llm_batch_annotate.cli resume examples/config/run_config_2.json example-grouped --poll-interval 30s --max-polls 20
```

## Artifacts to inspect

After a run finishes, look at:

- `metadata/manifest.json` for the lifecycle state and handle metadata.
- `metadata/summary.json` for the CLI-friendly summary snapshot.
- `raw/raw_outputs.jsonl` and `raw/raw_errors.jsonl` for provider results.
- `parsed/parsed_requests.jsonl` for request-level parsed payloads.
- `parsed/responses.jsonl` for per-row outputs, with `query_id` at top level for direct merge-back to the source table.
- `parsed/failures.jsonl` for parser, provider, flattening, or validation failures.
