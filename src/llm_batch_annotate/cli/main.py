from __future__ import annotations

import argparse
import csv
import importlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ..configs.models import RunConfig, SourceInputConfig
from ..contracts.base import ArtifactStore, BaseMessageBuilder, BaseParser, ExecutionProvider
from ..contracts.records import ComponentRef, ExecutionHandle
from ..enums import ArtifactKind, RunStatus, SourceFormat
from ..orchestration import TaskOrchestrator
from ..tasks.base import ComposedTaskBase


class CLIError(RuntimeError):
    """Raised when the CLI cannot complete the requested operation."""


def parse_poll_interval(value: str) -> float:
    text = value.strip().lower()
    match = re.fullmatch(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]*)", text)
    if match is None:
        msg = f"invalid poll interval: {value!r}"
        raise argparse.ArgumentTypeError(msg)

    amount = float(match.group("amount"))
    if amount < 0:
        msg = "poll interval must be non-negative"
        raise argparse.ArgumentTypeError(msg)

    unit = match.group("unit") or "s"
    unit_scale = {
        "s": 1.0,
        "sec": 1.0,
        "secs": 1.0,
        "second": 1.0,
        "seconds": 1.0,
        "m": 60.0,
        "min": 60.0,
        "mins": 60.0,
        "minute": 60.0,
        "minutes": 60.0,
        "h": 3600.0,
        "hr": 3600.0,
        "hrs": 3600.0,
        "hour": 3600.0,
        "hours": 3600.0,
    }
    scale = unit_scale.get(unit)
    if scale is None:
        msg = f"unsupported poll interval unit: {unit!r}"
        raise argparse.ArgumentTypeError(msg)
    return amount * scale


def add_polling_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--poll-interval",
        dest="poll_interval_seconds",
        type=parse_poll_interval,
        default=0.0,
        help="Time between polls, for example '30s', '2m', or '1h'.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        dest="poll_interval_seconds",
        type=float,
        help="Legacy alias for --poll-interval using raw seconds.",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=None,
        help="Maximum number of polling iterations before stopping.",
    )
    parser.add_argument(
        "--no-poll-until-terminal",
        action="store_true",
        help="Poll exactly once instead of waiting for terminal execution status.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-batch-annotate", description="Run LLM batch annotation workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a workflow from a serialized RunConfig JSON file.")
    run_parser.add_argument("config", type=Path, help="Path to a RunConfig JSON file.")
    run_parser.add_argument("--run-id", help="Override the generated run identifier.")
    add_polling_arguments(run_parser)
    run_parser.set_defaults(handler=run_command)

    resume_parser = subparsers.add_parser("resume", help="Resume or poll an existing workflow run.")
    resume_parser.add_argument("config", type=Path, help="Path to a RunConfig JSON file.")
    resume_parser.add_argument("run_id", help="Existing run identifier to resume.")
    add_polling_arguments(resume_parser)
    resume_parser.set_defaults(handler=resume_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2

    try:
        return int(handler(args))
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 1


def run_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_run_config(config_path)
    orchestrator = build_orchestrator(config)
    if args.run_id and orchestrator.has_run(args.run_id):
        state = orchestrator.resume(
            args.run_id,
            poll_until_terminal=not args.no_poll_until_terminal,
            poll_interval_seconds=args.poll_interval_seconds,
            max_polls=args.max_polls,
        )
    else:
        source_rows = load_source_rows(config.source_input)
        state = orchestrator.run(
            source_rows,
            run_id=args.run_id,
            poll_until_terminal=not args.no_poll_until_terminal,
            poll_interval_seconds=args.poll_interval_seconds,
            max_polls=args.max_polls,
        )

    summary = build_cli_summary(state)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if state.manifest.status is RunStatus.SUCCEEDED else 1


def resume_command(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_run_config(config_path)
    orchestrator = build_orchestrator(config)
    if not orchestrator.has_run(args.run_id):
        msg = f"run does not exist: {args.run_id}"
        raise CLIError(msg)

    effective_max_polls = 1 if args.no_poll_until_terminal and args.max_polls is None else args.max_polls
    print(
        f"[{_current_time_text()}] Resuming run {args.run_id} with poll_interval={args.poll_interval_seconds:.2f}s.",
        file=sys.stderr,
    )
    state = orchestrator.resume(
        args.run_id,
        poll_until_terminal=not args.no_poll_until_terminal,
        poll_interval_seconds=args.poll_interval_seconds,
        max_polls=effective_max_polls,
        on_poll=build_resume_progress_reporter(stream=sys.stderr),
    )
    print(build_resume_outcome_message(state), file=sys.stderr)

    summary = build_cli_summary(state)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if state.manifest.status is RunStatus.SUCCEEDED else 1


def build_resume_progress_reporter(*, stream: Any) -> Any:
    def reporter(state: Any, poll_number: int, total_polls: int | None) -> None:
        completed, failed, total = aggregate_request_progress(state.execution_handles)
        total_text = "?" if total_polls is None else str(total_polls)
        status_text = summarize_execution_status(state.execution_handles)
        print(
            (
                f"[{_current_time_text()}] poll {poll_number}/{total_text} "
                f"status={status_text} processed={completed} failed={failed} total={total}"
            ),
            file=stream,
        )

    return reporter


def build_resume_outcome_message(state: Any) -> str:
    completed, failed, total = aggregate_request_progress(state.execution_handles)
    return (
        f"[{_current_time_text()}] resume finished "
        f"run_id={state.manifest.run_id} status={state.manifest.status.value} "
        f"processed={completed} failed={failed} total={total} "
        f"parsed_requests={len(state.parsed_requests)} annotations={len(state.annotations)} failures={len(state.failures)}"
    )


def aggregate_request_progress(handles: list[ExecutionHandle]) -> tuple[int, int, int]:
    processed_total = 0
    failed_total = 0
    request_total = 0
    for handle in handles:
        processed, failed, total = request_progress_counts(handle)
        processed_total += processed
        failed_total += failed
        request_total += total
    return processed_total, failed_total, request_total


def request_progress_counts(handle: ExecutionHandle) -> tuple[int, int, int]:
    request_counts = handle.provider_metadata.get("request_counts", {})
    if isinstance(request_counts, dict):
        completed = int(request_counts.get("completed", 0) or 0)
        failed = int(request_counts.get("failed", 0) or 0)
        total = request_counts.get("total")
        if total is None:
            total = handle.request_count or 0
        return completed, failed, int(total)

    total = int(handle.request_count or 0)
    status = str(handle.status.value)
    if status == "succeeded":
        return total, 0, total
    if status == "failed":
        return 0, total, total
    if status == "partial":
        return max(total - 1, 0), min(total, 1), total
    return 0, 0, total


def summarize_execution_status(handles: list[ExecutionHandle]) -> str:
    if not handles:
        return "no-handles"
    statuses = sorted({handle.status.value for handle in handles})
    return ",".join(statuses)


def _current_time_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def load_run_config(config_path: Path) -> RunConfig:
    try:
        raw_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = f"config file does not exist: {config_path}"
        raise CLIError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = f"config file is not valid JSON: {config_path}"
        raise CLIError(msg) from exc

    if not isinstance(raw_payload, dict):
        msg = "config file must contain a JSON object"
        raise CLIError(msg)

    payload = resolve_run_config_paths(raw_payload, config_path.parent)
    try:
        return RunConfig.model_validate(payload)
    except Exception as exc:
        msg = f"config validation failed: {exc}"
        raise CLIError(msg) from exc


def resolve_run_config_paths(payload: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = json.loads(json.dumps(payload))

    source_input = dict(resolved.get("source_input", {}))
    source_path = source_input.get("path")
    if isinstance(source_path, str):
        source_input["path"] = str(resolve_relative_path(base_dir, source_path))
    resolved["source_input"] = source_input

    artifact_store = dict(resolved.get("artifact_store", {}))
    artifact_store_config = dict(artifact_store.get("config", {}))
    root_dir = artifact_store_config.get("root_dir")
    if isinstance(root_dir, str):
        artifact_store_config["root_dir"] = str(resolve_relative_path(base_dir, root_dir))
    artifact_store["config"] = artifact_store_config
    resolved["artifact_store"] = artifact_store

    prompt_assets = dict(resolved.get("prompt_assets", {}))
    asset_root = prompt_assets.get("asset_root")
    if isinstance(asset_root, str):
        prompt_assets["asset_root"] = str(resolve_relative_path(base_dir, asset_root))
        asset_base = Path(prompt_assets["asset_root"])
    else:
        asset_base = base_dir

    for field_name in (
        "system_prompt_path",
        "user_prompt_template_path",
        "few_shot_examples_path",
        "response_schema_path",
    ):
        asset_path = prompt_assets.get(field_name)
        if isinstance(asset_path, str) and asset_root is None:
            prompt_assets[field_name] = str(resolve_relative_path(asset_base, asset_path))

    asset_map = dict(prompt_assets.get("assets", {}))
    if asset_root is None:
        for asset_name, asset_path in asset_map.items():
            if isinstance(asset_path, str):
                asset_map[asset_name] = str(resolve_relative_path(asset_base, asset_path))
    prompt_assets["assets"] = asset_map
    resolved["prompt_assets"] = prompt_assets
    return resolved


def resolve_relative_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def build_orchestrator(config: RunConfig) -> TaskOrchestrator:
    task = instantiate_component_from_ref(config.task)
    if not isinstance(task, ComposedTaskBase):
        msg = "task component must resolve to a ComposedTaskBase instance"
        raise CLIError(msg)

    builder = instantiate_component_from_ref(config.builder)
    if not isinstance(builder, BaseMessageBuilder):
        msg = "builder component must resolve to a BaseMessageBuilder instance"
        raise CLIError(msg)

    parser = instantiate_component_from_ref(config.parser)
    if not isinstance(parser, BaseParser):
        msg = "parser component must resolve to a BaseParser instance"
        raise CLIError(msg)

    provider = instantiate_component_from_ref(config.provider.component)
    if not isinstance(provider, ExecutionProvider):
        msg = "provider component must resolve to an ExecutionProvider instance"
        raise CLIError(msg)

    artifact_store = instantiate_component_from_ref(config.artifact_store.component)
    if not isinstance(artifact_store, ArtifactStore):
        msg = "artifact store component must resolve to an ArtifactStore instance"
        raise CLIError(msg)

    return TaskOrchestrator(
        task=task,
        builder=builder,
        parser=parser,
        provider=provider,
        artifact_store=artifact_store,
        config=config,
    )


def import_string(import_path: str) -> Any:
    if ":" in import_path:
        module_name, attribute_name = import_path.split(":", 1)
    else:
        module_name, _, attribute_name = import_path.rpartition(".")
    if not module_name or not attribute_name:
        msg = f"invalid import path: {import_path!r}"
        raise CLIError(msg)

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        msg = f"could not import module {module_name!r} for component {import_path!r}"
        raise CLIError(msg) from exc

    try:
        return getattr(module, attribute_name)
    except AttributeError as exc:
        msg = f"module {module_name!r} does not define {attribute_name!r}"
        raise CLIError(msg) from exc


def instantiate_component_from_ref(component: ComponentRef) -> Any:
    target = import_string(component.import_path)
    if callable(target):
        try:
            return target(**component.settings)
        except TypeError as exc:
            msg = f"failed to instantiate component {component.import_path!r}: {exc}"
            raise CLIError(msg) from exc
    if component.settings:
        msg = f"component {component.import_path!r} is not callable but settings were provided"
        raise CLIError(msg)
    return target


def load_source_rows(source_input: SourceInputConfig) -> list[dict[str, object]]:
    source_path = Path(source_input.path)
    if source_input.format is SourceFormat.CSV:
        return load_delimited_rows(source_path, delimiter=",")
    if source_input.format is SourceFormat.TSV:
        return load_delimited_rows(source_path, delimiter="\t")
    if source_input.format is SourceFormat.JSONL:
        return load_jsonl_rows(source_path)
    if source_input.format is SourceFormat.PARQUET:
        msg = "parquet input is not supported by the CLI without an additional reader dependency"
        raise CLIError(msg)
    msg = f"unsupported source format: {source_input.format.value}"
    raise CLIError(msg)


def load_delimited_rows(path: Path, *, delimiter: str) -> list[dict[str, object]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]
    except FileNotFoundError as exc:
        msg = f"source file does not exist: {path}"
        raise CLIError(msg) from exc


def load_jsonl_rows(path: Path) -> list[dict[str, object]]:
    try:
        rows: list[dict[str, object]] = []
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = raw_line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                msg = f"jsonl source contains invalid JSON on line {line_number}"
                raise CLIError(msg) from exc
            if not isinstance(row, dict):
                msg = f"jsonl source line {line_number} must decode to an object"
                raise CLIError(msg)
            rows.append(row)
        return rows
    except FileNotFoundError as exc:
        msg = f"source file does not exist: {path}"
        raise CLIError(msg) from exc


def build_cli_summary(state: Any) -> dict[str, Any]:
    manifest = state.manifest
    return {
        "run_id": manifest.run_id,
        "run_name": manifest.run_name,
        "status": manifest.status.value,
        "counts": {
            "units": len(state.units),
            "groups": len(state.groups),
            "requests": len(state.requests),
            "execution_handles": len(state.execution_handles),
            "raw_outputs": len(state.raw_outputs),
            "raw_errors": len(state.raw_errors),
            "parsed_requests": len(state.parsed_requests),
            "annotations": len(state.annotations),
            "failures": len(state.failures),
        },
        "artifacts": {
            artifact_kind.value: artifact_ref.relative_path
            for artifact_kind, artifact_ref in manifest.artifacts.items()
        },
        "manifest_path": (
            manifest.artifacts[ArtifactKind.MANIFEST].relative_path
            if ArtifactKind.MANIFEST in manifest.artifacts
            else None
        ),
    }


__all__ = [
    "CLIError",
    "build_cli_summary",
    "build_orchestrator",
    "build_parser",
    "import_string",
    "instantiate_component_from_ref",
    "load_run_config",
    "load_source_rows",
    "main",
    "parse_poll_interval",
    "resume_command",
    "resolve_run_config_paths",
    "run_command",
]
