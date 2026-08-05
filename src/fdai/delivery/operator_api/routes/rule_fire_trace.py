"""Read-only ``GET /audit/{correlation_id}/trace`` route.

Reconstructs the full pipeline trace for one correlation id so an
on-call can answer "why did rule X fire" without hand-grepping the
audit log. Reader-role gate; GET-only.

Registered by :func:`~fdai.delivery.operator_api.main.build_app` only when
:attr:`~fdai.delivery.operator_api.main.OperatorApiConfig.trace_reader` is set.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.audit.rule_fire_trace import AuditTraceReader, build_rule_fire_trace

DEFAULT_ROUTE_PATH = "/audit/{correlation_id}/trace"


def make_rule_fire_trace_route(
    *,
    reader: AuditTraceReader,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return the named read-only route serving one trace by correlation id."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        correlation_id = request.path_params.get("correlation_id", "")
        if not correlation_id:
            return _error(400, "correlation_id path parameter is required")
        if len(correlation_id) > 256:
            return _error(400, "correlation_id is too long")

        items = await reader.read_items(correlation_id)
        trace = build_rule_fire_trace(correlation_id, items)
        if trace is None:
            return _error(404, f"no audit items for correlation_id {correlation_id!r}")

        return JSONResponse(trace.as_json())

    return Route(path, handler, methods=["GET"], name="rule_fire_trace")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["DEFAULT_ROUTE_PATH", "make_rule_fire_trace_route"]
