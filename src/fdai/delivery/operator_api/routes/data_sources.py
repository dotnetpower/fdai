"""Authenticated read-source availability manifest for the operator console."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.operator_api.application.conversation.capabilities.data_source_contract import (
    ReadDataSourceStatus,
    SourceAvailability,
)

AuthorizeOid = Callable[[Request], Awaitable[str]]


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
