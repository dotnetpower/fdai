"""Reader-gated projection of Muninn-owned detection readiness snapshots."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.operator_api.projections.detection_readiness import (
    DetectionReadinessReader,
    project_detection_readiness,
)

DEFAULT_ROUTE_PATH = "/detection-readiness"


def make_detection_readiness_route(
    *,
    reader: DetectionReadinessReader,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a read-only route over agent-owned persisted snapshots."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        try:
            payload = await project_detection_readiness(reader)
        except ValueError:
            return _error(500, "detection readiness store returned an invalid snapshot")
        return JSONResponse(payload)

    return Route(path, handler, methods=["GET"])


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "DetectionReadinessReader",
    "make_detection_readiness_route",
    "project_detection_readiness",
]
