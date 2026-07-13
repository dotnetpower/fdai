"""Read-only ``GET /inventory/graph`` route.

The route projects a CSP-neutral inventory snapshot for the operator console.
It owns query validation and response shaping only; cloud discovery stays
behind the injected provider at the composition root.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DEFAULT_ROUTE_PATH = "/inventory/graph"
_ALLOWED_LINKS = frozenset({"contains", "attached_to", "depends_on"})

InventoryGraphProvider = Callable[
    [str | None, int, tuple[str, ...]],
    Awaitable[Mapping[str, Any]],
]


def make_inventory_graph_route(
    *,
    provider: InventoryGraphProvider,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Reader-gated route serving one inventory graph projection."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        scope = request.query_params.get("scope") or None
        try:
            depth = int(request.query_params.get("depth", "4"))
        except ValueError:
            return _error(400, "depth must be an integer")
        if not 1 <= depth <= 8:
            return _error(400, "depth must be between 1 and 8")

        raw_links: Sequence[str] = request.query_params.getlist("link")
        if not raw_links:
            include = request.query_params.get("include", "")
            raw_links = tuple(part.strip() for part in include.split(",") if part.strip())
        links = tuple(dict.fromkeys(raw_links or ("contains", "attached_to", "depends_on")))
        unknown = sorted(set(links) - _ALLOWED_LINKS)
        if unknown:
            return _error(400, f"unsupported link type(s): {', '.join(unknown)}")

        payload = dict(await provider(scope, depth, links))
        resources = payload.get("resources")
        graph_links = payload.get("links")
        if not isinstance(resources, (list, tuple)) or not isinstance(graph_links, (list, tuple)):
            return _error(500, "inventory graph provider returned an invalid payload")
        payload.update(
            {
                "scope": scope,
                "depth": depth,
                "included_link_types": list(links),
                "resources": list(resources),
                "links": list(graph_links),
                "views": list(payload.get("views", ())),
            }
        )
        return JSONResponse(payload)

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = ["DEFAULT_ROUTE_PATH", "InventoryGraphProvider", "make_inventory_graph_route"]