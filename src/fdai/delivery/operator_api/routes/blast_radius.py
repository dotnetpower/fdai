"""Read-only ``GET /simulate/blast-radius`` route.

Optional route the app factory registers when
:attr:`~fdai.delivery.operator_api.main.OperatorApiConfig.blast_radius_graph`
is set. Purely a projection: the caller receives the depth-N reachable
set from a target Resource id, computed by
:mod:`fdai.core.risk_gate.blast_radius_simulator` against an injected
:class:`~fdai.core.risk_gate.blast_radius_simulator.OntologyGraph`.

Contract
--------
- GET-only; no mutation surface.
- Query params: ``target`` (required), ``depth`` (default 2, capped at
  :data:`~fdai.core.risk_gate.blast_radius_simulator.MAX_TRAVERSAL_DEPTH`),
  ``link`` (repeatable; MUST resolve to a link type the injected graph
  declares).
- Response: JSON payload of the report (see
  :meth:`~fdai.core.risk_gate.blast_radius_simulator.BlastRadiusReport.as_json`).
- Errors: 400 for malformed input, 422 for a link type the graph does
  not know, 500 only for unexpected exceptions.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.risk_gate.blast_radius_simulator import (
    MAX_TRAVERSAL_DEPTH,
    BlastRadiusRequest,
    OntologyGraph,
    TraversalDepthExceededError,
    UnknownLinkTypeError,
    simulate_blast_radius,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ROUTE_PATH = "/simulate/blast-radius"
DEFAULT_DEPTH = 2


def make_blast_radius_route(
    *,
    graph: OntologyGraph,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Starlette :class:`Route` wrapping the simulator."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        target = request.query_params.get("target")
        if not target:
            return _error(400, "query param 'target' is required")
        if len(target) > 512:
            return _error(400, "query param 'target' is too long")

        depth_raw = request.query_params.get("depth", str(DEFAULT_DEPTH))
        try:
            depth = int(depth_raw)
        except ValueError:
            return _error(400, f"query param 'depth' MUST be an integer, got {depth_raw!r}")
        if depth < 1 or depth > 8:
            return _error(400, "query param 'depth' MUST be in [1, 8]")

        links = tuple(request.query_params.getlist("link"))
        if not links:
            return _error(400, "query param 'link' is required (repeatable)")
        if len(links) > 32:
            return _error(400, "too many 'link' parameters (max 32)")
        if any(len(name) > 128 for name in links):
            return _error(400, "'link' name is too long (max 128 chars)")

        try:
            report = simulate_blast_radius(
                graph,
                BlastRadiusRequest(
                    target=target,
                    traversal_depth=depth,
                    traversal_links=links,
                ),
            )
        except TraversalDepthExceededError:
            return _error(
                400,
                f"depth exceeds cap {MAX_TRAVERSAL_DEPTH}; ask for a smaller subgraph",
            )
        except UnknownLinkTypeError as exc:
            return _error(422, str(exc))
        except ValueError as exc:
            return _error(400, str(exc))

        return JSONResponse(report.as_json())

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["DEFAULT_DEPTH", "DEFAULT_ROUTE_PATH", "make_blast_radius_route"]
