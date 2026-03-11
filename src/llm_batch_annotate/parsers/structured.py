from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..configs.models import RunConfig
from ..contracts.records import RawOutputRecord
from .base import BaseOutputParser


class StructuredOutputParser(BaseOutputParser):
    def __init__(
        self,
        *,
        payload_field_candidates: Sequence[str] | None = None,
        item_list_fields: Sequence[str] | None = None,
        unit_id_field: str = "unit_id",
    ) -> None:
        super().__init__(item_list_fields=item_list_fields, unit_id_field=unit_id_field)
        self.payload_field_candidates = tuple(
            payload_field_candidates or ("parsed", "content", "output_text", "text", "response")
        )

    def extract_payload(self, raw_output: RawOutputRecord, config: RunConfig) -> Mapping[str, Any]:
        del config
        candidate = self.extract_structured_candidate(raw_output.payload)
        return {"structured_output": candidate}

    def extract_structured_candidate(self, payload: Mapping[str, Any]) -> Any:
        for field_name in self.payload_field_candidates:
            if field_name not in payload:
                continue

            candidate = payload[field_name]
            if field_name == "response" and isinstance(candidate, Mapping):
                return self.extract_structured_candidate(candidate)
            return candidate

        return dict(payload)

    def deserialize_payload(self, payload: Mapping[str, Any], config: RunConfig) -> Mapping[str, Any]:
        del config
        candidate = payload.get("structured_output", payload)
        return self.coerce_structured_output(candidate)

    def coerce_structured_output(self, candidate: Any) -> dict[str, Any]:
        if isinstance(candidate, Mapping):
            return dict(candidate)

        if isinstance(candidate, list):
            return {"items": candidate}

        if isinstance(candidate, str):
            text = candidate.strip()
            if not text:
                msg = "structured output text is empty"
                raise ValueError(msg)
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                msg = "structured output is not valid JSON"
                raise ValueError(msg) from exc
            return self.coerce_structured_output(decoded)

        msg = "structured output must be a mapping, a list, or JSON text"
        raise ValueError(msg)
