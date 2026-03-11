# `llm-batch-annotate`

`llm-batch-annotate` is a Python package for running reproducible LLM annotation workflows over tabular datasets. It materializes units from source rows, groups them into provider requests, submits them through an execution adapter, parses structured outputs, validates coverage, and writes run artifacts for auditability.

## Highlights

- single-unit and grouped annotation workflows
- provider-agnostic task, builder, parser, and artifact abstractions
- concrete OpenAI Batch adapter
- resumable CLI-driven runs with persisted manifests
- example configs, prompts, schemas, and sample data under `examples/`

## Installation

When the package is published:

```bash
pip install llm-batch-annotate
```

From a local checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .[test,docs]
```

## Quickstart

Single-unit example:

```bash
export OPEN_AI_KEY="your-key"
llm-batch-annotate run examples/config/run_config.json --run-id example-single --no-poll-until-terminal
llm-batch-annotate resume examples/config/run_config.json example-single --poll-interval 2m
```

Grouped example:

```bash
export OPEN_AI_KEY="your-key"
llm-batch-annotate run examples/config/run_config_2.json --run-id example-grouped --no-poll-until-terminal
llm-batch-annotate resume examples/config/run_config_2.json example-grouped --poll-interval 2m
```

## Documentation

Project documentation is intended to be hosted on Read the Docs. The Sphinx source lives under `docs/`.

Planned public docs include:

- installation
- quickstart
- CLI reference
- config reference
- OpenAI Batch provider guide
- worked examples
- API reference
- development and release notes

## Repository layout

- `src/llm_batch_annotate/`: package source
- `examples/`: tracked example inputs and configs
- `tests/`: pytest suite
- `docs/`: Sphinx documentation source

Generated example runs are written to `examples/runs/` and are intentionally excluded from version control.
