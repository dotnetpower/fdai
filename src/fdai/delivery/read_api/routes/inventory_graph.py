"""Read-only ``GET /inventory/graph`` route.

The route projects a CSP-neutral inventory snapshot for the operator console.
It owns query validation and response shaping only; cloud discovery stays
behind the injected provider at the composition root.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, TypeGuard

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
_MAX_PROVIDER_RESOURCES = 5000
_MAX_PROVIDER_LINKS = 40_000
_MAX_PROVIDER_VIEWS = 1000
_TRUNCATION_REASONS = frozenset(
    {"resource_limit", "adjacent_edge_limit", "internal_edge_limit", "source_limit"}
)


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
        resource_cap = limit if root is not None else _MAX_PROVIDER_RESOURCES
        link_cap = max(64, limit * 8) if root is not None else _MAX_PROVIDER_LINKS
        if not _valid_provider_payload(payload, resource_cap=resource_cap, link_cap=link_cap):
            return _error(500, "inventory graph provider returned an invalid payload")
        resources = payload["resources"]
        graph_links = payload["links"]
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
                "truncated": payload.get("truncated", False),
                "truncation_reasons": list(payload.get("truncation_reasons", ())),
            }
        )
        return JSONResponse(payload)

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


def _valid_provider_payload(
    payload: Mapping[str, Any],
    *,
    resource_cap: int,
    link_cap: int,
) -> bool:
    resources = payload.get("resources")
    links = payload.get("links")
    views = payload.get("views", ())
    truncated = payload.get("truncated", False)
    truncation_reasons = payload.get("truncation_reasons", ())
    active_view = payload.get("active_view")
    if (
        not isinstance(resources, (list, tuple))
        or not isinstance(links, (list, tuple))
        or not isinstance(views, (list, tuple))
        or len(resources) > resource_cap
        or len(links) > link_cap
        or len(views) > _MAX_PROVIDER_VIEWS
        or not isinstance(truncated, bool)
        or not isinstance(truncation_reasons, (list, tuple))
        or any(reason not in _TRUNCATION_REASONS for reason in truncation_reasons)
        or (not truncated and bool(truncation_reasons))
        or (active_view is not None and not _non_empty_string(active_view))
    ):
        return False

    resource_ids: set[str] = set()
    for resource in resources:
        if not isinstance(resource, Mapping):
            return False
        resource_id = resource.get("id")
        if (
            not _non_empty_string(resource_id)
            or not _non_empty_string(resource.get("type"))
            or resource_id in resource_ids
        ):
            return False
        resource_ids.add(resource_id)

    for link in links:
        if not isinstance(link, Mapping):
            return False
        source = link.get("source")
        target = link.get("target")
        link_type = link.get("type")
        if (
            not _non_empty_string(source)
            or not _non_empty_string(target)
            or link_type not in _ALLOWED_LINKS
            or source not in resource_ids
            or target not in resource_ids
        ):
            return False

    return all(isinstance(view, Mapping) and _non_empty_string(view.get("id")) for view in views)


def _non_empty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "InventoryGraphProvider",
    "InventoryGraphViewNotFoundError",
    "make_inventory_graph_route",
]
