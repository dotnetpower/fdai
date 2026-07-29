"""Read-only ``GET /inventory/graph`` route.

The route projects a CSP-neutral inventory snapshot for the operator console.
It owns query validation and response shaping only; cloud discovery stays
behind the injected provider at the composition root.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError

DEFAULT_ROUTE_PATH = "/inventory/graph"
_ALLOWED_LINKS = frozenset({"contains", "attached_to", "depends_on"})
_DEFAULT_LIMIT = 500
_MAX_LIMIT = 1000
_MAX_LINK_FILTER_CHARS = 512
_MAX_LINK_FILTER_VALUES = 64


class InventoryGraphProvider(Protocol):
    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> Mapping[str, Any]: ...


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
        root = request.query_params.get("root") or None
        if root is not None and len(root) > 512:
            return _error(400, "root must be at most 512 characters")
        if scope is not None and root is not None:
            return _error(400, "scope and root cannot be combined")
        try:
            depth = int(request.query_params.get("depth", "4"))
        except ValueError:
            return _error(400, "depth must be an integer")
        if not 1 <= depth <= 8:
            return _error(400, "depth must be between 1 and 8")
        try:
            limit = int(request.query_params.get("limit", str(_DEFAULT_LIMIT)))
        except ValueError:
            return _error(400, "limit must be an integer")
        if not 1 <= limit <= _MAX_LIMIT:
            return _error(400, f"limit must be between 1 and {_MAX_LIMIT}")
        if root is None and "limit" in request.query_params:
            return _error(400, "limit requires root")

        raw_links: Sequence[str] = request.query_params.getlist("link")
        if len(raw_links) > _MAX_LINK_FILTER_VALUES or any(
            len(value) > _MAX_LINK_FILTER_CHARS for value in raw_links
        ):
            return _error(400, "link filter is too large")
        if not raw_links:
            include = request.query_params.get("include", "")
            if len(include) > _MAX_LINK_FILTER_CHARS:
                return _error(400, "include filter is too large")
            raw_links = tuple(part.strip() for part in include.split(",") if part.strip())
        links = tuple(dict.fromkeys(raw_links or ("contains", "attached_to", "depends_on")))
        unknown = sorted(set(links) - _ALLOWED_LINKS)
        if unknown:
            return _error(400, f"unsupported link type(s): {', '.join(unknown)}")

        try:
            if root is None:
                payload = dict(await provider(scope, depth, links))
            else:
                payload = dict(
                    await provider(
                        scope,
                        depth,
                        links,
                        root=root,
                        limit=limit,
                    )
                )
        except InventoryGraphViewNotFoundError as exc:
            return _error(404, str(exc))
        resources = payload.get("resources")
        graph_links = payload.get("links")
        if not isinstance(resources, (list, tuple)) or not isinstance(graph_links, (list, tuple)):
            return _error(500, "inventory graph provider returned an invalid payload")
        payload.update(
            {
                "scope": scope,
                "root": root,
                "depth": depth,
                "limit": limit,
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


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "InventoryGraphProvider",
    "InventoryGraphViewNotFoundError",
    "make_inventory_graph_route",
]
