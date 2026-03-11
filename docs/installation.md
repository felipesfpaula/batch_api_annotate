# Installation

## Runtime install

Install the package from PyPI once it is published:

```bash
pip install llm-batch-annotate
```

For local development from a checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --no-build-isolation -e .[test,docs]
```

## Python version

The current baseline is Python 3.12.

## Credentials

The bundled examples use `OPEN_AI_KEY` because the example configs set `request_options.api_key_env_var` to that name:

```bash
export OPEN_AI_KEY="sk-..."
```

If you prefer `OPENAI_API_KEY`, change the config field accordingly.
