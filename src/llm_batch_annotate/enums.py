from __future__ import annotations

from enum import StrEnum


class TaskKind(StrEnum):
    SINGLE = "single"
    GROUPED = "grouped"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class ProviderKind(StrEnum):
    OPENAI_BATCH = "openai_batch"
    CUSTOM = "custom"


class ArtifactStoreKind(StrEnum):
    LOCAL = "local"


class ArtifactKind(StrEnum):
    RUN_CONFIG = "run_config"
    MANIFEST = "manifest"
    SUMMARY = "summary"
    UNITS = "units"
    GROUPS = "groups"
    REQUESTS = "requests"
    RAW_OUTPUTS = "raw_outputs"
    RAW_ERRORS = "raw_errors"
    PARSED_REQUESTS = "parsed_requests"
    RESPONSES = "responses"
    FAILURES = "failures"


class ArtifactFormat(StrEnum):
    JSON = "json"
    JSONL = "jsonl"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class FailureKind(StrEnum):
    REQUEST_CONSTRUCTION = "request_construction"
    PROVIDER_SUBMISSION = "provider_submission"
    PROVIDER_EXECUTION = "provider_execution"
    PARSE = "parse"
    FLATTEN = "flatten"
    VALIDATION = "validation"
    RETRIEVAL = "retrieval"


class SourceFormat(StrEnum):
    CSV = "csv"
    TSV = "tsv"
    JSONL = "jsonl"
    PARQUET = "parquet"


class GroupingStrategy(StrEnum):
    FIXED_SIZE = "fixed_size"
