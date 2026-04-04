from __future__ import annotations

import json
from pathlib import Path

from llm_batch_annotate.cli import import_string, load_run_config, main, parse_poll_interval


def write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("query_id,query\nq-1,red shoes\nq-2,black boots\nq-3,green sandals\n", encoding="utf-8")


def write_prompt_assets(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "user.txt").write_text("Annotate grouped items: {row_ids_csv}", encoding="utf-8")


def write_config(tmp_path: Path, *, provider_settings: dict[str, object] | None = None) -> Path:
    config = {
        "run_metadata": {"run_name": "cli-phase"},
        "source_input": {"path": "data/input.csv", "format": "csv", "row_id_column": "query_id"},
        "task_kind": "grouped",
        "task": {
            "import_path": "llm_batch_annotate.GroupedTaskBase",
            "settings": {
                "required_input_columns": ["query"],
                "unit_field_columns": ["query"],
            },
        },
        "builder": {
            "import_path": "llm_batch_annotate.SimpleTemplateBuilder",
            "settings": {},
        },
        "parser": {"import_path": "llm_batch_annotate.StructuredOutputParser"},
        "provider": {
            "component": {
                "import_path": "tests.support_cli_provider.CLIFakeProvider",
                "settings": dict(provider_settings or {}),
            },
            "config": {"provider_kind": "custom", "settings": {}},
        },
        "artifact_store": {
            "component": {"import_path": "llm_batch_annotate.LocalArtifactStore"},
            "config": {"root_dir": "runs"},
        },
        "grouping": {"strategy": "fixed_size", "group_size": 2},
        "prompt_assets": {
            "asset_root": "prompts",
            "user_prompt_template_path": "user.txt",
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def test_import_string_loads_builtin_component() -> None:
    loaded = import_string("llm_batch_annotate.GroupedTaskBase")

    assert loaded.__name__ == "GroupedTaskBase"


def test_load_run_config_resolves_paths_relative_to_config_file(tmp_path: Path) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path)

    config = load_run_config(config_path)

    assert config.source_input.path == str((tmp_path / "data" / "input.csv").resolve())
    assert config.artifact_store.config.root_dir == str((tmp_path / "runs").resolve())
    assert config.prompt_assets.asset_root == str((tmp_path / "prompts").resolve())


def test_parse_poll_interval_accepts_seconds_minutes_and_hours() -> None:
    assert parse_poll_interval("30") == 30.0
    assert parse_poll_interval("45s") == 45.0
    assert parse_poll_interval("2m") == 120.0
    assert parse_poll_interval("1.5h") == 5400.0


def test_cli_run_executes_workflow_and_prints_summary(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path, provider_settings={"poll_statuses": ["running", "succeeded"]})

    exit_code = main(
        [
            "run",
            str(config_path),
            "--run-id",
            "run-cli-001",
            "--max-polls",
            "2",
            "--poll-interval-seconds",
            "0",
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert exit_code == 0
    assert summary["run_id"] == "run-cli-001"
    assert summary["status"] == "succeeded"
    assert summary["counts"]["annotations"] == 3
    assert (tmp_path / "runs" / "run-cli-001" / "metadata" / "manifest.json").exists()
    assert (tmp_path / "runs" / "run-cli-001" / "metadata" / "summary.json").exists()


def test_cli_run_returns_nonzero_for_partial_workflow(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(
        tmp_path,
        provider_settings={
            "poll_statuses": ["partial"],
            "request_behaviors": {"request-000001": {"error": "provider timeout"}},
        },
    )

    exit_code = main(["run", str(config_path), "--run-id", "run-cli-002", "--max-polls", "1"])

    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert exit_code == 1
    assert summary["status"] == "partial"
    assert summary["counts"]["failures"] == 2
    failures_path = tmp_path / "runs" / "run-cli-002" / "parsed" / "failures.jsonl"
    failure_kinds = [json.loads(line)["failure_kind"] for line in failures_path.read_text(encoding="utf-8").splitlines()]
    assert failure_kinds == ["provider_execution", "validation"]


def test_cli_run_can_return_running_summary_without_retrieval(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path, provider_settings={"poll_statuses": ["running"]})

    exit_code = main(["run", str(config_path), "--run-id", "run-cli-003", "--no-poll-until-terminal"])

    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert exit_code == 1
    assert summary["status"] == "running"
    assert summary["counts"]["raw_outputs"] == 0
    assert summary["counts"]["annotations"] == 0
    assert summary["counts"]["failures"] == 0


def test_cli_run_reuses_existing_run_id_as_resume(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path, provider_settings={"poll_statuses": ["running", "succeeded"]})

    first_exit_code = main(["run", str(config_path), "--run-id", "run-cli-004", "--no-poll-until-terminal"])
    first_summary = json.loads(capsys.readouterr().out)

    second_exit_code = main(["run", str(config_path), "--run-id", "run-cli-004", "--max-polls", "1"])
    second_summary = json.loads(capsys.readouterr().out)

    assert first_exit_code == 1
    assert first_summary["status"] == "running"
    assert second_exit_code == 0
    assert second_summary["status"] == "succeeded"
    assert second_summary["counts"]["annotations"] == 3


def test_cli_resume_command_polls_existing_run(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path, provider_settings={"poll_statuses": ["running", "succeeded"]})

    first_exit_code = main(["run", str(config_path), "--run-id", "run-cli-005", "--no-poll-until-terminal"])
    first_summary = json.loads(capsys.readouterr().out)

    second_exit_code = main(["resume", str(config_path), "run-cli-005", "--max-polls", "1"])
    second_summary = json.loads(capsys.readouterr().out)

    assert first_exit_code == 1
    assert first_summary["status"] == "running"
    assert second_exit_code == 0
    assert second_summary["status"] == "succeeded"
    assert second_summary["counts"]["parsed_requests"] == 2


def test_cli_resume_command_prints_progress_messages(tmp_path: Path, capsys) -> None:
    write_csv(tmp_path / "data" / "input.csv")
    write_prompt_assets(tmp_path / "prompts")
    config_path = write_config(tmp_path, provider_settings={"poll_statuses": ["running", "succeeded"]})

    main(["run", str(config_path), "--run-id", "run-cli-006", "--no-poll-until-terminal"])
    capsys.readouterr()

    exit_code = main(["resume", str(config_path), "run-cli-006", "--max-polls", "1", "--poll-interval", "2m"])
    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert exit_code == 0
    assert summary["status"] == "succeeded"
    assert "Resuming run run-cli-006 with poll_interval=120.00s." in captured.err
    assert "poll 1/1 status=succeeded processed=2 failed=0 total=2" in captured.err
    assert "resume finished run_id=run-cli-006 status=succeeded" in captured.err
