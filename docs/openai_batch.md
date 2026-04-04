# OpenAI Batch Provider

`OpenAIBatchProvider` is the first concrete execution adapter. It turns framework `RequestRecord` values into an OpenAI Batch input file, uploads the file, creates a batch job, polls job state, and downloads output or error files when the batch is terminal.

## Current defaults

- provider kind: `openai_batch`
- supported endpoints: `/v1/chat/completions` and `/v1/responses`
- completion window: `24h`
- default base URL: `https://api.openai.com`

## API key resolution

The provider resolves the API key in this order:

1. `request_options.api_key`
2. provider constructor argument
3. environment variable named by `request_options.api_key_env_var`
4. `OPENAI_API_KEY` if `api_key_env_var` is not overridden

The bundled examples override the environment variable name to `OPEN_AI_KEY`.

## Structured outputs

The examples use `/v1/responses` with a JSON schema under `request_options.body.text.format`. That matches the built-in `StructuredOutputParser`, which expects the model to produce JSON compatible with the configured schema.

For `task_kind: "single"`, the parser accepts either a bare object or a one-item collection and can infer the single configured row id from request context when it is omitted. Single-item OpenAI Batch requests also reuse that row id as the Batch `custom_id`.

For `task_kind: "grouped"`, the provider keeps generated request ids for Batch `custom_id` values and carries member row ids in request metadata. Grouped responses still need explicit item-level values for the configured row-id field.

After parsing, the user-facing artifact is `parsed/responses.jsonl`. Each row uses the configured row-id field name at top level, which means the same file can be merged back to the original dataset without renaming columns. Single-item rows omit `group_id`; grouped rows keep it.

For `gpt-5-mini`, the example configs intentionally omit `temperature`.

## Resume flow

Typical usage is:

1. submit a run with `run --no-poll-until-terminal`
2. wait while the batch validates or runs on the OpenAI side
3. call `resume` until the run becomes terminal
4. let the orchestrator retrieve, parse, flatten, and finalize automatically

## Failure modes

A provider-level success does not automatically mean parsing succeeded. Inspect both:

- `raw/raw_outputs.jsonl` for provider-returned outputs
- `parsed/responses.jsonl` for the finalized per-row outputs
- `parsed/failures.jsonl` for parser, flattening, or validation failures
