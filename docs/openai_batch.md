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
- `parsed/failures.jsonl` for parser, flattening, or validation failures
