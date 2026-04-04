# Changelog

## 0.1.2 - 2026-04-04

### Changed

- Replaced `source_input.unit_id_column` with required `source_input.row_id_column` as the canonical user-facing source identifier.
- Renamed the parsed output artifact from `parsed/flattened_annotations.jsonl` to `parsed/responses.jsonl`.
- Persisted the configured row-id field name at top level in `parsed/responses.jsonl` so results can be merged back to source tables directly.
- Reused source row ids as OpenAI Batch `custom_id` values for single-item runs.
- Kept grouped request ids generated internally while preserving member row ids in request metadata and parsed responses.

### Parsing and Response Behavior

- Single-item parsing now accepts a bare object or a one-item collection without requiring the row id in model output.
- Grouped parsing still requires explicit row-id values on each returned item.
- Single-item persisted responses no longer include `group_id`; grouped responses still do.

### Documentation and Release Tooling

- Updated the examples and docs to use `query_id`, `row_id_column`, and `parsed/responses.jsonl`.
- Added release notes to the docs and exposed a changelog link in package metadata.
- Prepared the release workflow to create a GitHub Release on version tags in addition to publishing to TestPyPI and PyPI.
- Fixed the GitHub Release workflow so the artifact-only release job passes the repository explicitly to `gh release create`.
