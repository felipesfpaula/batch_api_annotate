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
- `.github/workflows/release.yml` for GitHub Releases plus trusted publishing on version tags

## One-time external setup

Before the automation can publish docs or packages, configure:

1. a GitHub repository with the default branch `main`
2. a Read the Docs project connected to the GitHub repository
3. a TestPyPI trusted publisher for the release workflow
4. a PyPI trusted publisher for the release workflow
5. GitHub environments named `testpypi` and `pypi`
6. if you want versioned Read the Docs pages beyond `latest`, enable version builds for tags in the RTD project settings

## Release flow

1. merge changes into `main`
2. ensure CI is green
3. update `src/llm_batch_annotate/_version.py`, release notes in `CHANGELOG.md`, and any publish-facing docs
4. create and push a tag such as `v0.1.2`
5. let the release workflow build the distribution once
6. create the GitHub Release from that tag and attach the built artifacts
7. publish the built artifacts to TestPyPI
8. promote the exact same artifacts to PyPI after approval
9. verify the Read the Docs `latest` build on `main`, and any tag-specific RTD version if you enabled versioned docs

## Documentation source of truth

`README.md` is the short package landing page for GitHub and PyPI. The canonical long-form documentation lives under `docs/`. The retired `docs.md` and `docs_specs.md` files are intentionally no longer part of the tracked source tree.
