"""Service-owned Starlette routes for the frozen minimal Operator HTTP surface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdai_service_contracts import (
    AuditQuery,
    HilQueueQuery,
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
from starlette.responses import JSONResponse, Response
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
        page = await read_model.list_audit(
            AuditQuery(
                limit=_parse_limit(request),
                cursor=_bounded_query(request, "cursor", maximum=1024),
                correlation_id=_bounded_query(request, "correlation_id", maximum=256),
            )
        )
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
        return JSONResponse((await read_model.list_incidents()).to_dict())

    async def incident_attention_stream(request: Request) -> Response:
        authorize(request)
        raise ProjectionUnavailableError("service-local incident stream relay is not ported")

    async def get_rca(request: Request) -> Response:
        authorize(request)
        return JSONResponse((await read_model.get_rca()).to_dict())

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
