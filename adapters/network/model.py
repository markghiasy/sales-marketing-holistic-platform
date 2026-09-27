from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ScenarioData = dict[str, Any]
GraphSnapshot = dict[str, Any]


def timestamp(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class GraphQuery(BaseModel):
    focus: str = "person:owner"
    view: Literal["compact", "explorer"] = "explorer"
    as_of: datetime = Field(default_factory=lambda: timestamp("2026-09-27T12:00:00Z"))
    search: str = ""
    function: str = ""
    organization: str = ""
    project: str = ""
    mode: Literal["current", "history"] = "current"
    include_pending: bool = False
    expand: str = ""

    @field_validator("as_of")
    @classmethod
    def normalize_time(cls, value):
        return timestamp(value)
