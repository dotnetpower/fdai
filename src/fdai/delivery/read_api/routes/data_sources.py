"""Authenticated read-source availability manifest for the operator console."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

SourceAvailability = Literal["available", "unavailable", "unknown"]
AuthorizeOid = Callable[[Request], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ReadDataSourceStatus:
    """Composition-owned provenance for one console evidence source."""

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


def make_data_sources_route(
    *,
    sources: Sequence[ReadDataSourceStatus],
    authorize: AuthorizeOid,
) -> Route:
    """Return the Reader-gated manifest without probing or mutating providers."""

    by_key: Mapping[str, ReadDataSourceStatus] = {source.key: source for source in sources}
    if len(by_key) != len(sources):
        raise ValueError("read data source keys MUST be unique")
    routes = tuple(route for source in sources for route in source.routes)
    if len(set(routes)) != len(routes):
        raise ValueError("read data source routes MUST have unique owners")

    async def get_data_sources(request: Request) -> Response:
        await authorize(request)
        ordered = tuple(by_key[key] for key in sorted(by_key))
        return JSONResponse(
            {
                "surface": "read-data-sources",
                "sources": [source.to_dict() for source in ordered],
            }
        )

    return Route("/system/data-sources", get_data_sources, methods=["GET"])


__all__ = ["ReadDataSourceStatus", "SourceAvailability", "make_data_sources_route"]
