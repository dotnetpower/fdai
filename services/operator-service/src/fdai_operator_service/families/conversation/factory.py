"""Starlette route factory for the independently composed conversation family."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from fdai_operator_service.families.conversation.contracts import (
    ConversationAuthorizer,
    ConversationBoundaryError,
    ConversationProjectionReader,
    ConversationProposal,
    ConversationProposalOutbox,
    ConversationQuery,
    ConversationStreamReader,
    ConversationStreamRequest,
)
from fdai_operator_service.families.conversation.manifest import (
    CONVERSATION_ROUTE_MANIFEST,
    ConversationRouteSpec,
)
from fdai_operator_service.families.conversation.transport import (
    boundary_error_response,
    bounded_path_params,
    bounded_query,
    idempotency_key,
    last_event_id,
    read_json_body,
    response_from_contract,
    sse_frame,
    unavailable_response,
)
from fdai_operator_service.streaming.shutdown import shutting_down
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

type _Endpoint = Callable[[Request], Awaitable[Response]]


@dataclass(frozen=True, slots=True)
class ConversationFamilyDependencies:
    """Injected authority-free dependencies for all conversation family routes."""

    authorizer: ConversationAuthorizer
    projections: ConversationProjectionReader | None = None
    outbox: ConversationProposalOutbox | None = None
    streams: ConversationStreamReader | None = None


def build_conversation_routes(
    dependencies: ConversationFamilyDependencies,
) -> tuple[Route, ...]:
    """Build the frozen family surface without importing or executing FDAI runtime code."""
    return tuple(_route(spec, dependencies) for spec in CONVERSATION_ROUTE_MANIFEST)


def _route(spec: ConversationRouteSpec, dependencies: ConversationFamilyDependencies) -> Route:
    if spec.mode == "read":
        endpoint = _read_endpoint(spec, dependencies)
    elif spec.mode == "proposal":
        endpoint = _proposal_endpoint(spec, dependencies)
    else:
        endpoint = _stream_endpoint(spec, dependencies)
    return Route(spec.path, endpoint, methods=[spec.method], name=spec.name)


def _read_endpoint(
    spec: ConversationRouteSpec,
    dependencies: ConversationFamilyDependencies,
) -> _Endpoint:
    async def endpoint(request: Request) -> Response:
        if dependencies.projections is None:
            return unavailable_response("authoritative conversation projection")
        try:
            scope = await dependencies.authorizer.authorize(request, operation=spec.operation)
            result = await dependencies.projections.read(
                ConversationQuery(
                    operation=spec.operation,
                    scope=scope,
                    query=bounded_query(request),
                    path_params=bounded_path_params(request),
                )
            )
            return response_from_contract(result)
        except ConversationBoundaryError as exc:
            return boundary_error_response(exc)

    return endpoint


def _proposal_endpoint(
    spec: ConversationRouteSpec,
    dependencies: ConversationFamilyDependencies,
) -> _Endpoint:
    async def endpoint(request: Request) -> Response:
        if dependencies.outbox is None:
            return unavailable_response("conversation proposal outbox")
        try:
            scope = await dependencies.authorizer.authorize(request, operation=spec.operation)
            body = (
                await read_json_body(request, maximum=spec.max_body_bytes)
                if spec.max_body_bytes
                else {}
            )
            if spec.requires_confirmation and body.get("confirmed") is not True:
                raise ConversationBoundaryError(
                    409,
                    "confirmation_required",
                    "explicit confirmation is required",
                )
            query = bounded_query(request)
            path_params = bounded_path_params(request)
            proposal = ConversationProposal(
                operation=spec.operation,
                scope=scope,
                idempotency_key=idempotency_key(
                    request,
                    operation=spec.operation,
                    scope=scope,
                    body=body,
                    query=query,
                    path_params=path_params,
                ),
                body=body,
                query=query,
                path_params=path_params,
                confirmed=body.get("confirmed") is True,
                cancellation=spec.operation.endswith((".cancel", ".cancel_current", ".expire")),
            )
            receipt = await dependencies.outbox.append(proposal)
            return response_from_contract(receipt.response)
        except ConversationBoundaryError as exc:
            return boundary_error_response(exc)

    return endpoint


def _stream_endpoint(
    spec: ConversationRouteSpec,
    dependencies: ConversationFamilyDependencies,
) -> _Endpoint:
    async def endpoint(request: Request) -> Response:
        if dependencies.streams is None:
            return unavailable_response("conversation event stream")
        try:
            scope = await dependencies.authorizer.authorize(request, operation=spec.operation)
            body = (
                await read_json_body(request, maximum=spec.max_body_bytes)
                if spec.max_body_bytes
                else {}
            )
            query = bounded_query(request)
            path_params = bounded_path_params(request)
            stream_idempotency_key = (
                idempotency_key(
                    request,
                    operation=spec.operation,
                    scope=scope,
                    body=body,
                    query=query,
                    path_params=path_params,
                )
                if spec.method == "POST"
                else None
            )
            proposal_id: str | None = None
            if spec.method == "POST":
                if dependencies.outbox is None:
                    return unavailable_response("conversation proposal outbox")
                if stream_idempotency_key is None:
                    raise RuntimeError("POST stream idempotency key was not constructed")
                receipt = await dependencies.outbox.append(
                    ConversationProposal(
                        operation=spec.operation,
                        scope=scope,
                        idempotency_key=stream_idempotency_key,
                        body=body,
                        query=query,
                        path_params=path_params,
                    )
                )
                proposal_id = receipt.proposal_id
            stream_request = ConversationStreamRequest(
                operation=spec.operation,
                scope=scope,
                body=body,
                query=query,
                path_params=path_params,
                after_event_id=last_event_id(request),
                idempotency_key=stream_idempotency_key,
                proposal_id=proposal_id,
            )
            source = await dependencies.streams.open(stream_request)
        except ConversationBoundaryError as exc:
            return boundary_error_response(exc)

        async def events() -> AsyncIterator[bytes]:
            try:
                async for event in source:
                    if shutting_down(request) or await request.is_disconnected():
                        return
                    yield sse_frame(event)
            finally:
                await source.aclose()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return endpoint


__all__ = ["ConversationFamilyDependencies", "build_conversation_routes"]
