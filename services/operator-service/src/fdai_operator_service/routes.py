"""Service-owned Starlette routes for the frozen minimal Operator HTTP surface."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from fdai_operator_service.contracts import ApplicationLifecycle, ReadinessProbe
from fdai_operator_service.families.conversation import (
    CONVERSATION_ROUTE_MANIFEST,
    ConversationFamilyDependencies,
    build_conversation_routes,
)
from fdai_operator_service.families.iam import (
    IAM_FAMILY_MANIFEST,
    IamFamilyBindings,
    make_iam_family_routes,
)
from fdai_operator_service.families.operations import (
    OPERATIONS_ROUTE_MANIFEST,
    DurableReplayReader,
    EventProposalWriter,
    ProjectionReader,
    WebhookVerifier,
    build_operations_routes,
)
from fdai_operator_service.families.workflow import (
    WORKFLOW_FAMILY_ROUTE_MANIFEST,
    WorkflowPrincipalAuthorizer,
    WorkflowProposalWriter,
    WorkflowReadStore,
    build_workflow_family_routes,
)
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_operator_service.redaction import redact_projection

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


@dataclass(frozen=True, slots=True)
class RouteOwnership:
    """Declare one explicit method/path owner in the aggregate Operator surface."""

    method: str
    path: str
    owner: str


@dataclass(frozen=True, slots=True)
class OperatorRouteFamilies:
    """Hold the four independently extracted family dependency sets."""

    conversation: ConversationFamilyDependencies
    iam: IamFamilyBindings
    workflow_authorize: WorkflowPrincipalAuthorizer
    workflow_read_store: WorkflowReadStore
    workflow_proposal_writer: WorkflowProposalWriter
    operations_projection_reader: ProjectionReader
    operations_proposal_writer: EventProposalWriter
    operations_replay_reader: DurableReplayReader
    operations_webhook_verifier: WebhookVerifier


MINIMAL_ROUTE_MANIFEST: Final = (
    RouteOwnership("GET", "/audit", "minimal"),
    RouteOwnership("GET", "/audit/{correlation_id}/trace", "minimal"),
    RouteOwnership("GET", "/healthz", "minimal"),
    RouteOwnership("GET", "/hil-queue", "minimal"),
    RouteOwnership("GET", "/incidents", "minimal"),
    RouteOwnership("GET", "/incidents/stream", "minimal"),
    RouteOwnership("GET", "/kpi", "minimal"),
    RouteOwnership("GET", "/kpi/llm-cost", "minimal"),
    RouteOwnership("GET", "/notification-templates/incident-opened", "minimal"),
    RouteOwnership("GET", "/rca", "minimal"),
    RouteOwnership("GET", "/system/data-sources", "minimal"),
)


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
    route_families: OperatorRouteFamilies,
    readiness_probe: ReadinessProbe,
    cors_allow_origins: tuple[str, ...] = (),
    lifecycle: ApplicationLifecycle | None = None,
) -> Starlette:
    """Build the complete Operator API without executor or FDAI imports."""
    _validate_data_sources(data_sources)
    ownership = aggregate_route_manifest()

    def authorize(request: Request) -> OperatorPrincipal:
        return authenticator.require_any(request.headers.get("authorization"), READER_ROLES)

    async def readiness(_: Request) -> Response:
        try:
            ready = await readiness_probe()
        except Exception:  # noqa: BLE001 - dependency probes fail closed
            ready = False
        return JSONResponse(
            {"status": "ok" if ready else "not-ready"},
            status_code=200 if ready else 503,
        )

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
        return JSONResponse(redact_projection(page.to_dict()))

    async def get_kpi(request: Request) -> Response:
        authorize(request)
        return JSONResponse(redact_projection((await read_model.dashboard_metrics()).to_dict()))

    async def get_llm_cost(request: Request) -> Response:
        authorize(request)
        range_start, range_end = _llm_usage_range(request)
        projection = await read_model.llm_usage(range_start, range_end)
        return JSONResponse(redact_projection(projection.to_dict()))

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
        return JSONResponse(redact_projection(projection.to_dict(include_details=include_details)))

    async def get_incidents(request: Request) -> Response:
        authorize(request)
        query = _incident_query(request)
        try:
            projection = await read_model.list_incidents(query)
        except ValueError as exc:
            raise _BadQueryError(str(exc)) from exc
        return JSONResponse(redact_projection(projection.to_dict()))

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
        return JSONResponse(redact_projection(projection.to_dict()))

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
        return JSONResponse(redact_projection(projection.to_dict()))

    async def get_data_sources(request: Request) -> Response:
        authorize(request)
        ordered = sorted(data_sources, key=lambda source: source.key)
        return JSONResponse(
            redact_projection(
                {
                    "surface": "read-data-sources",
                    "sources": [source.to_dict() for source in ordered],
                }
            )
        )

    async def get_incident_opened_template(request: Request) -> Response:
        authorize(request)
        return JSONResponse(redact_projection(_incident_template_preview()))

    minimal_routes = [
        Route("/audit", get_audit, methods=["GET"], name="get_audit"),
        Route(
            "/audit/{correlation_id}/trace",
            rule_fire_trace,
            methods=["GET"],
            name="rule_fire_trace",
        ),
        Route("/healthz", readiness, methods=["GET"], name="healthz"),
        Route("/hil-queue", get_hil_queue, methods=["GET"], name="get_hil_queue"),
        Route("/incidents", get_incidents, methods=["GET"], name="panel:incidents"),
        Route(
            "/incidents/stream",
            incident_attention_stream,
            methods=["GET"],
            name="incident_attention_stream",
        ),
        Route("/kpi", get_kpi, methods=["GET"], name="get_kpi"),
        Route("/kpi/llm-cost", get_llm_cost, methods=["GET"], name="get_llm_cost"),
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
    family_routes = [
        *build_conversation_routes(route_families.conversation),
        *make_iam_family_routes(route_families.iam),
        *build_workflow_family_routes(
            authorize=route_families.workflow_authorize,
            read_store=route_families.workflow_read_store,
            proposal_writer=route_families.workflow_proposal_writer,
        ),
        *build_operations_routes(
            authenticator=authenticator,
            projection_reader=route_families.operations_projection_reader,
            proposal_writer=route_families.operations_proposal_writer,
            replay_reader=route_families.operations_replay_reader,
            webhook_verifier=route_families.operations_webhook_verifier,
        ),
    ]
    routes = [*minimal_routes, *family_routes]
    _validate_registered_routes(routes, ownership)
    middleware: list[Middleware] = [Middleware(SecurityHeadersMiddleware)]
    if cors_allow_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(cors_allow_origins),
                allow_methods=["GET", "POST", "PUT", "DELETE"],
                allow_headers=["Authorization", "Content-Type"],
            )
        )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        if lifecycle is not None:
            await lifecycle.start()
        try:
            yield
        finally:
            if lifecycle is not None:
                await lifecycle.aclose()

    return Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
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


def _llm_usage_range(request: Request) -> tuple[datetime, datetime]:
    values: list[datetime] = []
    for name in ("from", "to"):
        raw = _bounded_query(request, name, maximum=64)
        if raw is None:
            raise _BadQueryError(f"{name} MUST be provided")
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _BadQueryError(f"{name} MUST be an ISO 8601 timestamp") from exc
        if value.tzinfo is None:
            raise _BadQueryError(f"{name} MUST include a timezone")
        values.append(value.astimezone(UTC))
    range_start, range_end = values
    if range_end <= range_start:
        raise _BadQueryError("to MUST be later than from")
    if range_end - range_start > timedelta(days=90):
        raise _BadQueryError("LLM usage range MUST NOT exceed 90 days")
    return range_start, range_end


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
    data = json.dumps(
        redact_projection(projection.to_dict()),
        separators=(",", ":"),
        sort_keys=True,
    )
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


def aggregate_route_manifest() -> tuple[RouteOwnership, ...]:
    """Return the exact aggregate ownership manifest and reject duplicates."""
    ownership = (
        *MINIMAL_ROUTE_MANIFEST,
        *(
            RouteOwnership(item.method, item.path, "conversation")
            for item in CONVERSATION_ROUTE_MANIFEST
        ),
        *(RouteOwnership(item.method, item.path, "iam") for item in IAM_FAMILY_MANIFEST),
        *(
            RouteOwnership(item.method, item.path, "workflow")
            for item in WORKFLOW_FAMILY_ROUTE_MANIFEST
        ),
        *(
            RouteOwnership(item.method, item.path, "operations")
            for item in OPERATIONS_ROUTE_MANIFEST
        ),
    )
    identities = [(item.method, item.path) for item in ownership]
    if len(set(identities)) != len(identities):
        duplicates = sorted(
            identity for identity in set(identities) if identities.count(identity) > 1
        )
        raise ValueError(f"Operator route manifests have duplicate owners: {duplicates!r}")
    return ownership


def _validate_registered_routes(
    routes: Sequence[Route],
    ownership: Sequence[RouteOwnership],
) -> None:
    registered = {
        (method, route.path)
        for route in routes
        for method in (route.methods or set())
        if method not in {"HEAD", "OPTIONS"}
    }
    expected = {(item.method, item.path) for item in ownership}
    if registered != expected or len(routes) != len(ownership):
        raise ValueError("registered Operator routes MUST exactly match unique manifest ownership")


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


__all__ = [
    "MINIMAL_ROUTE_MANIFEST",
    "OperatorRouteFamilies",
    "RouteOwnership",
    "aggregate_route_manifest",
    "build_operator_app",
]
