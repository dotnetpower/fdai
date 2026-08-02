"""Read-only ``GET /kpi/promotion-gates`` route.

For each shipped ActionType, returns the promotion-gate progress row
computed against the injected
:class:`~fdai.core.measurement.promotion_gate.ShadowVerdictSource`.
An on-call sees at a glance which ActionTypes are green for
promotion and which are blocked (and by which criterion).

Registered by :func:`~fdai.delivery.operator_api.main.build_app` only when
:attr:`~fdai.delivery.operator_api.main.OperatorApiConfig.promotion_gate_source`
is set. Reader-role gate; GET-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.measurement.promotion_gate import (
    PromotionGateEvaluator,
    ShadowVerdictSource,
)
from fdai.shared.contracts.models import OntologyActionType

DEFAULT_ROUTE_PATH = "/kpi/promotion-gates"
DEFAULT_WINDOW_DAYS = 90


def make_promotion_gates_route(
    *,
    action_types: Sequence[OntologyActionType],
    source: ShadowVerdictSource,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
    default_window_days: int = DEFAULT_WINDOW_DAYS,
) -> Route:
    """Return a Starlette :class:`Route` serving the promotion-gate dashboard."""
    evaluator = PromotionGateEvaluator()

    async def handler(request: Request) -> Response:
        await authorize(request)
        window_raw = request.query_params.get("window_days")
        if window_raw is None:
            window_days: int | None = default_window_days
        else:
            try:
                window_days = int(window_raw)
            except ValueError:
                return _error(400, "window_days MUST be an integer")
            if window_days < 1:
                return _error(400, "window_days MUST be >= 1")
            if window_days > 365:
                # Cap at one year so a caller cannot request a datetime
                # arithmetic that overflows / returns unbounded rows.
                return _error(400, "window_days MUST be <= 365")

        filter_name = request.query_params.get("action_type")
        if filter_name is not None and len(filter_name) > 256:
            return _error(400, "action_type filter is too long")
        target = [at for at in action_types if filter_name is None or at.name == filter_name]
        if filter_name is not None and not target:
            return _error(404, f"unknown action_type {filter_name!r}")

        rows = evaluator.evaluate_many(target, source=source, window_days=window_days)
        return JSONResponse(
            {
                "window_days": window_days,
                "rows": [row.as_json() for row in rows],
                "ready_count": sum(1 for row in rows if row.ready),
                "blocked_count": sum(1 for row in rows if not row.ready),
            }
        )

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "DEFAULT_WINDOW_DAYS",
    "make_promotion_gates_route",
]
