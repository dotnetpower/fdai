"""Composition-owned data-source records used by conversation and HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SourceAvailability = Literal["available", "unavailable", "unknown"]


@dataclass(frozen=True, slots=True)
class ReadDataSourceStatus:
    """Describe one authoritative or unavailable console evidence source."""

    key: str
    source: str
    routes: tuple[str, ...]
    availability: SourceAvailability
    configured: bool
    reachable: bool | None
    authoritative: bool
    durable: bool | None
    synthetic: bool
    reason: str | None = None
    last_observed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.source:
            raise ValueError("read data source key and source MUST NOT be empty")
        if not self.routes or any(not route.startswith("/") for route in self.routes):
            raise ValueError("read data source routes MUST contain absolute paths")
        if self.synthetic and self.authoritative:
            raise ValueError("synthetic read data sources MUST NOT be authoritative")
        if self.availability == "available" and not self.configured:
            raise ValueError("an available read data source MUST be configured")
        if self.availability == "unavailable" and not self.reason:
            raise ValueError("an unavailable read data source MUST include a reason")
        if self.availability == "unavailable" and self.reachable is True:
            raise ValueError("an unavailable read data source MUST NOT be reachable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "routes": list(self.routes),
            "availability": self.availability,
            "configured": self.configured,
            "reachable": self.reachable,
            "authoritative": self.authoritative,
            "durable": self.durable,
            "synthetic": self.synthetic,
            "reason": self.reason,
            "last_observed_at": self.last_observed_at,
        }


__all__ = ["ReadDataSourceStatus", "SourceAvailability"]
