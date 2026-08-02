"""Reader-gated projection of Muninn-owned detection readiness snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.readiness import (
    DETECTION_READINESS_STATE_PREFIX,
    DetectionReadinessDecision,
    DetectionReadinessSnapshot,
)

DEFAULT_ROUTE_PATH = "/detection-readiness"
_MAX_TARGETS = 256


class DetectionReadinessReader(Protocol):
    async def read_states(self, prefix: str, *, limit: int) -> tuple[Mapping[str, Any], ...]: ...


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


async def project_detection_readiness(reader: DetectionReadinessReader) -> dict[str, Any]:
    """Strictly decode the current Muninn projection without re-judging it."""
    records = await reader.read_states(DETECTION_READINESS_STATE_PREFIX, limit=_MAX_TARGETS)
    snapshots = [
        DetectionReadinessSnapshot.model_validate(
            {name: record.get(name) for name in DetectionReadinessSnapshot.model_fields}
        )
        for record in records
    ]
    snapshots.sort(key=lambda item: item.resource_ref)
    counts = Counter(item.decision.value for item in snapshots)
    observed_at = max((item.generated_at for item in snapshots), default=None)
    return {
        "source": "muninn-state-snapshot",
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "target_count": len(snapshots),
        "counts": {
            decision.value: counts[decision.value] for decision in DetectionReadinessDecision
        },
        "targets": [item.model_dump(mode="json") for item in snapshots],
    }


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "DetectionReadinessReader",
    "make_detection_readiness_route",
    "project_detection_readiness",
]
