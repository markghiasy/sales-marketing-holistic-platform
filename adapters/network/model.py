from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ScenarioData = dict[str, Any]
GraphSnapshot = dict[str, Any]


def timestamp(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


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
    depth: int = Field(default=2, ge=1, le=3)
    min_activity: float = Field(default=0, ge=0, le=100)

    scopes: str = "direct,explicit"
    scope_window: Literal[0, 30, 90, 180] = 0
    scope_sort: Literal["recent", "frequency", "name"] = "recent"
    min_sessions: int = Field(default=0, ge=0, le=1000)

    @field_validator("scope_window", mode="before")
    @classmethod
    def parse_window(cls, value):
        if isinstance(value, str) and value in {"0", "30", "90", "180"}:
            return int(value)
        return value

    @field_validator("scopes")
    @classmethod
    def canonical_scopes(cls, value):
        order = ("direct", "explicit", "project", "organization")
        if value == "":
            return value
        values = [part.strip() for part in value.split(",")]
        if len(set(values)) != len(values) or any(part not in order for part in values):
            raise ValueError("scopes must be a unique CSV subset of " + ",".join(order))
        return ",".join(part for part in order if part in values)

    @field_validator("as_of")
    @classmethod
    def normalize_time(cls, value):
        return timestamp(value)
