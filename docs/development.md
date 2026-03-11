# Development and Release

## Local development

Create a virtual environment and install the editable package with test and docs dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --no-build-isolation -e .[test,docs]
```

Useful local commands:

```bash
pytest -q
python -m build
twine check dist/*
sphinx-build -b html docs docs/_build/html
```

## GitHub Actions

The repository includes:

- `.github/workflows/ci.yml` for tests, docs build, package build, `twine check`, and wheel install smoke testing
- `.github/workflows/release.yml` for trusted publishing on version tags

## One-time external setup

Before the automation can publish docs or packages, configure:

1. a GitHub repository with the default branch `main`
2. a Read the Docs project connected to the GitHub repository
3. a TestPyPI trusted publisher for the release workflow
4. a PyPI trusted publisher for the release workflow
5. GitHub environments named `testpypi` and `pypi`

## Release flow

1. merge changes into `main`
2. ensure CI is green
3. create and push a tag such as `v0.1.0`
4. let the release workflow build the distribution once
5. publish the built artifacts to TestPyPI
6. promote the exact same artifacts to PyPI after approval

## Documentation source of truth

`README.md` is the short package landing page for GitHub and PyPI. The canonical long-form documentation lives under `docs/`. The retired `docs.md` and `docs_specs.md` files are intentionally no longer part of the tracked source tree.
