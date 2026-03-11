from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrameworkModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )
