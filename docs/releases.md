# Releases

## v0.1.1

Release date: 2026-04-04

### Highlights

- The source-table identifier is now user-owned through `source_input.row_id_column`.
- The canonical parsed output is now `parsed/responses.jsonl`.
- Single-item runs no longer require the model to echo the row id when exactly one row is in scope.
- Single-item OpenAI Batch requests now reuse the source row id as the Batch `custom_id`.

### Breaking public contract changes

- `source_input.unit_id_column` has been replaced by required `source_input.row_id_column`.
- `parsed/flattened_annotations.jsonl` has been replaced by `parsed/responses.jsonl`.

### Response artifact shape

- Every row in `parsed/responses.jsonl` includes the configured row-id field at top level.
- Single-item rows omit `group_id`.
- Grouped rows keep `group_id`.

### Release surfaces

- PyPI package version: `0.1.1`
- GitHub release tag: `v0.1.1`
- Read the Docs latest build reflects this release series from the `main` branch

The repository-level changelog lives in [`CHANGELOG.md`](https://github.com/felipesfpaula/batch_api_annotate/blob/main/CHANGELOG.md).
