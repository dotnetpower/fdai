"""Bounded execution provenance values for channel-neutral conversation activity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MAX_ACTIVITY_TARGET_CHARS = 128


@dataclass(frozen=True, slots=True)
class ExecutionEndpoint:
    """One bounded HTTP endpoint path without an origin or credentials."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,255}", self.path):
            raise ValueError("activity endpoint path is invalid")
        if "//" in self.path:
            raise ValueError("activity endpoint path MUST NOT contain an origin")


@dataclass(frozen=True, slots=True)
class ExecutionTarget:
    """Additive execution provenance that never grants effect authority."""

    interface_kind: Literal["internal_query", "http", "cli", "sdk"]
    service: str
    component: str
    operation: str
    source_kind: str | None = None
    transport: Literal["event_bus", "in_process"] | None = None
    endpoint: ExecutionEndpoint | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("service", self.service),
            ("component", self.component),
            ("operation", self.operation),
            ("source_kind", self.source_kind),
        ):
            if value is not None and not re.fullmatch(
                rf"[A-Za-z0-9][A-Za-z0-9_.-]{{0,{MAX_ACTIVITY_TARGET_CHARS - 1}}}",
                value,
            ):
                raise ValueError(f"activity target {name} is invalid")
        if self.interface_kind == "http" and self.endpoint is None:
            raise ValueError("HTTP activity target MUST carry an endpoint")
        if self.interface_kind != "http" and self.endpoint is not None:
            raise ValueError("non-HTTP activity target MUST NOT carry an endpoint")
