"""Always-on audit, KPI, HIL queue, and health read routes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.delivery.operator_api.read_model import DEFAULT_LIMIT, ConsoleReadModel, clamp_limit
from fdai.delivery.operator_api.routes.audit_query import AuditQueryError, parse_audit_filters

_LOGGER = logging.getLogger(__name__)

AuthorizeOid = Callable[[Request], Awaitable[str]]
AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]


def make_core_read_routes(
    *,
    read_model: ConsoleReadModel,
    authorize_oid: AuthorizeOid,
    authorize_principal: AuthorizePrincipal,
    dev_mode: bool,
) -> tuple[Route, ...]:
    """Build the four always-on GET routes with their visibility gates."""

    async def get_audit(request: Request) -> Response:
        oid = await authorize_oid(request)
        try:
            limit = _parse_int_query(request, "limit", default=DEFAULT_LIMIT)
        except _BadQueryError as exc:
            return _error(400, str(exc))
        cursor = request.query_params.get("cursor")
        if cursor is not None and len(cursor) > 1024:
            return _error(400, "cursor is too long")
        try:
            correlation_id = request.query_params.get("correlation_id") or None
            if correlation_id is not None and len(correlation_id) > 256:
                return _error(400, "correlation_id MUST be at most 256 characters")
            filters = parse_audit_filters(request.query_params)
            page = await read_model.list_audit(
                limit=clamp_limit(limit),
                cursor=cursor,
                correlation_id=correlation_id,
                filters=filters,
            )
        except (AuditQueryError, ValueError) as exc:
            return _error(400, str(exc))
        _LOGGER.info("audit_page_served", extra={"actor": oid, "returned": len(page.items)})
        return JSONResponse(page.to_dict())

    async def get_kpi(request: Request) -> Response:
        oid = await authorize_oid(request)
        kpi = await read_model.dashboard_metrics()
        _LOGGER.info("kpi_served", extra={"actor": oid, "event_count": kpi.event_count})
        return JSONResponse(kpi.to_dict())

    async def get_hil_queue(request: Request) -> Response:
        principal = await authorize_principal(request)
        try:
            limit = _parse_int_query(request, "limit", default=DEFAULT_LIMIT)
        except _BadQueryError as exc:
            return _error(400, str(exc))
        detail_visible = dev_mode or has_capability(
            principal.roles,
            Capability.APPROVE_RUNTIME_HIL,
        )
        search = (request.query_params.get("q") or "").strip() or None
        if search is not None and len(search) > 200:
            return _error(400, "q MUST be at most 200 characters")
        page = await read_model.list_hil_queue(
            limit=clamp_limit(limit),
            search=search if detail_visible else None,
        )
        payload = page.to_dict()
        payload["detail_level"] = "full" if detail_visible else "count_only"
        if not detail_visible:
            payload["items"] = []
        _LOGGER.info(
            "hil_queue_served",
            extra={
                "actor": principal.oid,
                "returned": len(page.items) if detail_visible else 0,
                "detail_level": payload["detail_level"],
            },
        )
        return JSONResponse(payload)

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    return (
        Route("/audit", get_audit, methods=["GET"]),
        Route("/kpi", get_kpi, methods=["GET"]),
        Route("/hil-queue", get_hil_queue, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    )


def append_local_auth_route(
    routes: list[BaseRoute],
    *,
    profile: Mapping[str, object] | None,
) -> None:
    """Append the optional local-Azure-CLI identity projection."""
    if profile is None:
        return

    async def get_local_auth_profile(_: Request) -> Response:
        return JSONResponse(dict(profile))

    routes.append(Route("/local-auth/me", get_local_auth_profile, methods=["GET"]))


class _BadQueryError(ValueError):
    """A query string is malformed and should become an HTTP 400 response."""


def _parse_int_query(request: Request, name: str, *, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise _BadQueryError(f"query param {name!r} must be an integer, got {raw!r}") from exc


def _error(status: int, message: str) -> JSONResponse:
    body: dict[str, Any] = {"error": {"status": status, "message": message}}
    return JSONResponse(body, status_code=status)


__all__ = ["append_local_auth_route", "make_core_read_routes"]
