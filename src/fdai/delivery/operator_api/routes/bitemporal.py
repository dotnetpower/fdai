"""Read-only ``GET /audit/{correlation_id}/bitemporal`` route.

Reconstructs a resource-state snapshot as of a (system_time,
business_time) pair from the audit log. Reader-role gate; GET-only.

Query params:

- ``as_of``      RFC 3339 UTC timestamp; system-time cutoff. Required.
- ``effective``  RFC 3339 UTC timestamp; business-time cutoff. Optional
                 (defaults to ``as_of``). MUST be ``<= as_of``.
- ``resource_id`` The Resource id the snapshot describes. Required.

The ``correlation_id`` in the path scopes the audit-item read - the
route asks the injected trace reader for every item under that
correlation, then folds them into a
:class:`~fdai.core.audit.bitemporal.BitemporalSnapshot`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.audit.bitemporal import BitemporalQueryError, snapshot_at
from fdai.core.audit.rule_fire_trace import AuditTraceReader

DEFAULT_ROUTE_PATH = "/audit/{correlation_id}/bitemporal"


def make_bitemporal_route(
    *,
    reader: AuditTraceReader,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Starlette :class:`Route` serving bitemporal snapshots."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        correlation_id = request.path_params.get("correlation_id", "")
        if not correlation_id:
            return _error(400, "correlation_id path parameter is required")
        if len(correlation_id) > 256:
            return _error(400, "correlation_id is too long")

        resource_id = request.query_params.get("resource_id", "")
        if not resource_id:
            return _error(400, "query param 'resource_id' is required")
        if len(resource_id) > 512:
            return _error(400, "resource_id is too long")

        as_of_raw = request.query_params.get("as_of")
        if not as_of_raw:
            return _error(400, "query param 'as_of' is required")
        as_of = _parse_ts(as_of_raw)
        if as_of is None:
            return _error(400, f"as_of MUST be RFC 3339 UTC, got {as_of_raw!r}")

        effective_raw = request.query_params.get("effective")
        effective = _parse_ts(effective_raw) if effective_raw else None
        if effective_raw and effective is None:
            return _error(400, f"effective MUST be RFC 3339 UTC, got {effective_raw!r}")

        items = await reader.read_items(correlation_id)
        if not items:
            return _error(404, f"no audit items for correlation_id {correlation_id!r}")

        try:
            snap = snapshot_at(resource_id, items, as_of=as_of, effective=effective)
        except BitemporalQueryError as exc:
            return _error(400, str(exc))

        return JSONResponse(snap.as_json())

    return Route(path, handler, methods=["GET"])


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "message": message}},
        status_code=status,
    )


__all__ = ["DEFAULT_ROUTE_PATH", "make_bitemporal_route"]
