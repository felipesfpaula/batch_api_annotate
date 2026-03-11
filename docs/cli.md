# CLI

The package installs a single user-facing command:

```bash
llm-batch-annotate
```

## Commands

### `run`

Create a new run from a config file. If `--run-id` already exists, `run` resumes that existing run instead of submitting a new batch.

```bash
llm-batch-annotate run examples/config/run_config.json --run-id example-single --no-poll-until-terminal
```

### `resume`

Resume an existing run by `run_id` and print poll progress to `stderr`.

```bash
llm-batch-annotate resume examples/config/run_config.json example-single --poll-interval 2m --max-polls 10
```

## Polling options

- `--no-poll-until-terminal`: poll once and return.
- `--max-polls N`: cap the number of poll iterations.
- `--poll-interval VALUE`: friendly durations such as `30s`, `2m`, or `1h`.
- `--poll-interval-seconds N`: legacy raw-seconds alias.

## Progress output

The `resume` command prints one line per poll that includes:

- current local time
- `poll_number/total_polls`
- current batch status
- processed request count
- failed request count
- total request count

When the command stops, it prints a final summary line and then emits the JSON run summary on `stdout`.

## Exit codes

- `0`: the run finished with overall status `succeeded`
- `1`: the run finished in a non-success state or the CLI hit an error

## Path resolution

Paths in the JSON config are resolved relative to the config file location. That applies to:

- `source_input.path`
- `artifact_store.config.root_dir`
- prompt asset paths when `prompt_assets.asset_root` is absent
- `prompt_assets.asset_root` itself
