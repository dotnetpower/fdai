"""Read-only ``GET /audit/{correlation_id}/what-if`` route.

Re-runs a past event against a **pre-registered** what-if evaluator
(see :attr:`~fdai.delivery.operator_api.main.OperatorApiConfig.what_if_evaluators`).
Reader-role gate; GET-only. The route is a pure projection: the sandbox
in :mod:`fdai.core.audit.what_if_replay` guarantees no state mutation.

Why a pre-registered evaluator (not inline JSON on the request)?

- Uploading a full alternate catalog per request would be a
  write-shaped payload on a read-only surface.
- Pre-registration lets the ops team version and audit each what-if
  scenario the same way the shipped rule catalog is versioned.

Query params:

- ``scenario`` (required)  name of a registered evaluator.

The evaluator receives the reconstructed event and returns match
verdicts; the route diffs against the original audit's action kinds
and ships both sides as JSON.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.audit.rule_fire_trace import AuditTraceReader
from fdai.core.audit.what_if_replay import (
    EventReconstructionError,
    WhatIfEvaluator,
    replay_with_what_if,
)

DEFAULT_ROUTE_PATH = "/audit/{correlation_id}/what-if"


def make_what_if_route(
    *,
    reader: AuditTraceReader,
    evaluators: Mapping[str, WhatIfEvaluator],
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Starlette :class:`Route` serving what-if replays."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        correlation_id = request.path_params.get("correlation_id", "")
        if not correlation_id:
            return _error(400, "correlation_id path parameter is required")
        # Bound the input so an attacker cannot amplify a 4xx into a
        # megabyte-scale reflected error body or log line. Real
        # correlation ids are UUIDs / event-id shapes < 128 chars.
        if len(correlation_id) > 256:
            return _error(400, "correlation_id is too long")

        scenario = request.query_params.get("scenario", "")
        if not scenario:
            return _error(400, "query param 'scenario' is required")
        if len(scenario) > 128:
            return _error(400, "scenario is too long")
        evaluator = evaluators.get(scenario)
        if evaluator is None:
            return _error(
                404,
                f"unknown scenario {scenario!r}; registered: {sorted(evaluators)!r}",
            )

        items = await reader.read_items(correlation_id)
        if not items:
            return _error(404, f"no audit items for correlation_id {correlation_id!r}")

        try:
            report = replay_with_what_if(correlation_id, items, evaluator)
        except EventReconstructionError as exc:
            return _error(422, str(exc))

        return JSONResponse(
            {
                "scenario": scenario,
                **report.as_json(),
            }
        )

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["DEFAULT_ROUTE_PATH", "make_what_if_route"]
