"""Service-owned Starlette routes for the frozen minimal Operator HTTP surface."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Final, Literal, cast

from fdai_service_contracts import (
    AuditQuery,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentQuery,
    JsonObject,
    OperatorPrincipal,
    OperatorReadModel,
    OperatorRole,
    ReadDataSource,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.projections import ProjectionUnavailableError

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 500
READER_ROLES: Final = frozenset(
    {
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.OWNER,
    }
)
APPROVAL_ROLES: Final = frozenset({OperatorRole.APPROVER, OperatorRole.OWNER})


class SecurityHeadersMiddleware:
    """Add non-cacheable JSON safety headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                headers.extend(
                    (
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_headers)


def build_operator_app(
    *,
    authenticator: OperatorAuthenticator,
    read_model: OperatorReadModel,
    data_sources: Sequence[ReadDataSource],
    cors_allow_origins: tuple[str, ...] = (),
) -> Starlette:
    """Build the frozen minimal Operator API without executor or FDAI imports."""
    _validate_data_sources(data_sources)

    def authorize(request: Request) -> OperatorPrincipal:
        return authenticator.require_any(request.headers.get("authorization"), READER_ROLES)

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def get_audit(request: Request) -> Response:
        authorize(request)
        try:
            page = await read_model.list_audit(
                AuditQuery(
                    limit=_parse_limit(request),
                    cursor=_bounded_query(request, "cursor", maximum=1024),
                    correlation_id=_bounded_query(request, "correlation_id", maximum=256),
                )
            )
        except ValueError as exc:
            raise _BadQueryError(str(exc)) from exc
        return JSONResponse(page.to_dict())

    async def get_kpi(request: Request) -> Response:
        authorize(request)
        return JSONResponse((await read_model.dashboard_metrics()).to_dict())

    async def get_hil_queue(request: Request) -> Response:
        principal = authorize(request)
        include_details = not principal.roles.isdisjoint(APPROVAL_ROLES)
        search = _bounded_query(request, "q", maximum=200) if include_details else None
        projection = await read_model.list_hil_queue(
            HilQueueQuery(
                limit=_parse_limit(request),
                search=search,
                include_details=include_details,
            )
        )
        return JSONResponse(projection.to_dict(include_details=include_details))

    async def get_incidents(request: Request) -> Response:
        authorize(request)
        query = _incident_query(request)
        try:
            projection = await read_model.list_incidents(query)
        except ValueError as exc:
            raise _BadQueryError(str(exc)) from exc
        return JSONResponse(projection.to_dict())

    async def incident_attention_stream(request: Request) -> Response:
        authorize(request)
        after_seq = _last_event_id(request)
        initial = await read_model.incident_attention(
            IncidentAttentionQuery(after_seq=after_seq, limit=50)
        )

        async def events() -> AsyncIterator[bytes]:
            current = after_seq
            projection = initial
            while not await request.is_disconnected():
                if projection is not None:
                    current = projection.sequence
                    yield _sse_frame(projection)
                else:
                    yield b": keepalive\n\n"
                await asyncio.sleep(2.0)
                projection = await read_model.incident_attention(
                    IncidentAttentionQuery(after_seq=current, limit=50)
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    async def get_rca(request: Request) -> Response:
        authorize(request)
        correlation_id = _bounded_query(request, "correlation", maximum=256) or _bounded_query(
            request, "correlation_id", maximum=256
        )
        if correlation_id is None:
            raise _BadQueryError("correlation MUST be provided")
        projection = await read_model.get_rca(correlation_id)
        if projection is None:
            return _error(404, f"no audit evidence for correlation {correlation_id!r}")
        return JSONResponse(projection.to_dict())

    async def rule_fire_trace(request: Request) -> Response:
        authorize(request)
        correlation_id = request.path_params.get("correlation_id", "")
        if not isinstance(correlation_id, str) or not correlation_id:
            return _error(400, "correlation_id path parameter is required")
        if len(correlation_id) > 256:
            return _error(400, "correlation_id is too long")
        projection = await read_model.get_rule_fire_trace(correlation_id)
        if projection is None:
            return _error(404, f"no audit items for correlation_id {correlation_id!r}")
        return JSONResponse(projection.to_dict())

    async def get_data_sources(request: Request) -> Response:
        authorize(request)
        ordered = sorted(data_sources, key=lambda source: source.key)
        return JSONResponse(
            {
                "surface": "read-data-sources",
                "sources": [source.to_dict() for source in ordered],
            }
        )

    async def get_incident_opened_template(request: Request) -> Response:
        authorize(request)
        return JSONResponse(_incident_template_preview())

    routes = [
        Route("/audit", get_audit, methods=["GET"], name="get_audit"),
        Route(
            "/audit/{correlation_id}/trace",
            rule_fire_trace,
            methods=["GET"],
            name="rule_fire_trace",
        ),
        Route("/healthz", healthz, methods=["GET"], name="healthz"),
        Route("/hil-queue", get_hil_queue, methods=["GET"], name="get_hil_queue"),
        Route("/incidents", get_incidents, methods=["GET"], name="panel:incidents"),
        Route(
            "/incidents/stream",
            incident_attention_stream,
            methods=["GET"],
            name="incident_attention_stream",
        ),
        Route("/kpi", get_kpi, methods=["GET"], name="get_kpi"),
        Route(
            "/notification-templates/incident-opened",
            get_incident_opened_template,
            methods=["GET"],
            name="get_incident_opened_template",
        ),
        Route("/rca", get_rca, methods=["GET"], name="panel:rca"),
        Route(
            "/system/data-sources",
            get_data_sources,
            methods=["GET"],
            name="get_data_sources",
        ),
    ]
    middleware: list[Middleware] = [Middleware(SecurityHeadersMiddleware)]
    if cors_allow_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(cors_allow_origins),
                allow_methods=["GET"],
                allow_headers=["Authorization", "Content-Type"],
            )
        )
    return Starlette(
        routes=routes,
        middleware=middleware,
        exception_handlers={
            AuthenticationError: _authentication_error,
            AuthorizationError: _authorization_error,
            ProjectionUnavailableError: _projection_unavailable,
            _BadQueryError: _bad_query_error,
        },
    )


async def _authentication_error(_: Request, exc: Exception) -> Response:
    return _error(401, str(exc))


async def _authorization_error(_: Request, exc: Exception) -> Response:
    return _error(403, str(exc))


async def _projection_unavailable(_: Request, __: Exception) -> Response:
    return _error(503, "authoritative Operator projection is unavailable")


async def _bad_query_error(_: Request, exc: Exception) -> Response:
    return _error(400, str(exc))


def _parse_limit(request: Request) -> int:
    raw = request.query_params.get("limit")
    if raw is None:
        return DEFAULT_LIMIT
    try:
        value = int(raw)
    except ValueError as exc:
        raise _BadQueryError(f"query param 'limit' must be an integer, got {raw!r}") from exc
    return min(MAX_LIMIT, max(1, value))


def _bounded_query(request: Request, name: str, *, maximum: int) -> str | None:
    value = request.query_params.get(name)
    if value is not None and len(value) > maximum:
        raise _BadQueryError(f"{name} MUST be at most {maximum} characters")
    return value or None


def _incident_query(request: Request) -> IncidentQuery:
    status = request.query_params.get("status", "active")
    if status not in {"active", "resolved", "all"}:
        raise _BadQueryError("status MUST be one of: active, resolved, all")
    vertical = (request.query_params.get("vertical") or "").replace("-", "_") or None
    if vertical not in {None, "resilience", "change_safety", "cost_governance", "unknown"}:
        raise _BadQueryError(
            "vertical MUST be one of: resilience, change-safety, cost-governance, unknown"
        )
    return IncidentQuery(
        status=cast(Literal["active", "resolved", "all"], status),
        limit=_parse_limit(request),
        cursor=_bounded_query(request, "cursor", maximum=1024),
        vertical=vertical,
        correlation_id=_bounded_query(request, "correlation_id", maximum=256),
    )


def _last_event_id(request: Request) -> int | None:
    value = request.headers.get("last-event-id")
    if value is None or value == "":
        return None
    try:
        sequence = int(value)
    except ValueError as exc:
        raise _BadQueryError("Last-Event-ID MUST be a non-negative integer") from exc
    if sequence < 0:
        raise _BadQueryError("Last-Event-ID MUST be a non-negative integer")
    return sequence


def _sse_frame(projection: IncidentAttentionProjection) -> bytes:
    data = json.dumps(projection.to_dict(), separators=(",", ":"), sort_keys=True)
    return f"id: {projection.sequence}\nevent: incident-attention\ndata: {data}\n\n".encode()


class _BadQueryError(ValueError):
    """A bounded Operator query parameter is malformed."""


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


def _validate_data_sources(sources: Sequence[ReadDataSource]) -> None:
    keys = [source.key for source in sources]
    routes = [route for source in sources for route in source.routes]
    if len(set(keys)) != len(keys):
        raise ValueError("read data source keys MUST be unique")
    if len(set(routes)) != len(routes):
        raise ValueError("read data source routes MUST have unique owners")


def _incident_template_preview() -> JsonObject:
    incident_id = "00000000-0000-0000-0000-000000000000"
    subject = "Incident opened: SEV2"
    plain_text = "Synthetic incident-open template preview."
    html = f"<html><body><h1>{subject}</h1><p>{plain_text}</p><p>{incident_id}</p></body></html>"
    return {
        "key": "incident-opened",
        "subject": subject,
        "plain_text": plain_text,
        "html": html,
    }


__all__ = ["build_operator_app"]
