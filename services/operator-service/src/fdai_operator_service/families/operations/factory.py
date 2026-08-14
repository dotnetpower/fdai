"""Starlette route factory for non-privileged Operator operations."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.families.operations.contracts import (
    DurableReplayReader,
    EventProposal,
    EventProposalWriter,
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
    ProposalConflictError,
    ReplayEvent,
    ReplayQuery,
    ReportPdfEncoder,
    ReportPdfEncodingError,
    WebhookVerifier,
)
from fdai_operator_service.families.operations.manifest import (
    OPERATIONS_ROUTE_MANIFEST,
    OperationRoute,
)
from fdai_operator_service.redaction import redact_projection
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 500
MAX_CURSOR_CHARS: Final = 1024
MAX_QUERY_VALUES: Final = 64
MAX_QUERY_VALUE_CHARS: Final = 2048
MAX_BODY_BYTES: Final = 256 * 1024
MAX_SSE_FRAME_BYTES: Final = 256 * 1024
_EVENT_NAME: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_CONTRIBUTOR_ROLES: Final = frozenset({OperatorRole.CONTRIBUTOR, OperatorRole.OWNER})


@dataclass(frozen=True, slots=True)
class PanelRoute:
    """Declare one injected read panel with its exact legacy path and name."""

    path: str
    name: str
    operation: str
    roles: frozenset[OperatorRole] = OPERATIONS_ROUTE_MANIFEST[0].roles


def build_operations_routes(
    *,
    authenticator: OperatorAuthenticator,
    projection_reader: ProjectionReader,
    proposal_writer: EventProposalWriter,
    replay_reader: DurableReplayReader,
    webhook_verifier: WebhookVerifier,
    report_pdf_encoder: ReportPdfEncoder | None = None,
    panels: Sequence[PanelRoute] = (),
) -> tuple[Route, ...]:
    """Build exact legacy routes over injected read, proposal, and replay ports."""
    entries = (*OPERATIONS_ROUTE_MANIFEST, *(_panel_entry(panel) for panel in panels))
    _validate_entries(entries)
    return tuple(
        _build_route(
            entry,
            authenticator=authenticator,
            projection_reader=projection_reader,
            proposal_writer=proposal_writer,
            replay_reader=replay_reader,
            webhook_verifier=webhook_verifier,
            report_pdf_encoder=report_pdf_encoder,
        )
        for entry in entries
    )


def _build_route(
    entry: OperationRoute,
    *,
    authenticator: OperatorAuthenticator,
    projection_reader: ProjectionReader,
    proposal_writer: EventProposalWriter,
    replay_reader: DurableReplayReader,
    webhook_verifier: WebhookVerifier,
    report_pdf_encoder: ReportPdfEncoder | None,
) -> Route:
    async def endpoint(request: Request) -> Response:
        if entry.kind == "webhook":
            return await _webhook(request, entry, proposal_writer, webhook_verifier)
        try:
            principal = authenticator.require_any(
                request.headers.get("authorization"),
                _CONTRIBUTOR_ROLES if entry.kind == "proposal" else entry.roles,
            )
        except AuthenticationError as exc:
            return _error(401, str(exc))
        except AuthorizationError as exc:
            return _error(403, str(exc))
        if entry.kind == "proposal":
            return await _proposal(
                request,
                entry,
                principal,
                proposal_writer,
                replay_reader,
            )
        if entry.kind == "stream":
            return await _stream(request, entry, principal, replay_reader)
        return await _projection(
            request,
            entry,
            principal,
            projection_reader,
            report_pdf_encoder,
        )

    endpoint.__name__ = entry.name
    return Route(entry.path, endpoint, methods=[entry.method], name=entry.name)


async def _projection(
    request: Request,
    entry: OperationRoute,
    principal: OperatorPrincipal,
    reader: ProjectionReader,
    report_pdf_encoder: ReportPdfEncoder | None,
) -> Response:
    try:
        params = _bounded_params(request)
        requested_format = params.get("format", ("json",))[-1]
        if entry.operation == "report.render" and requested_format == "pdf":
            if report_pdf_encoder is None:
                return _error(400, "unknown format 'pdf'")
            report_id = request.path_params.get("report_id", "")
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", str(report_id)) is None:
                return _error(400, "malformed report id")
        payload = await reader.read(
            ProjectionQuery(
                operation=entry.operation,
                principal_id=principal.subject_id,
                path={key: str(value) for key, value in request.path_params.items()},
                params=params,
                limit=_limit(params),
                cursor=_cursor(params),
            )
        )
        redacted_value = redact_projection(payload)
        if not isinstance(redacted_value, Mapping):
            return _error(503, "authoritative report projection is malformed")
        redacted = cast(Mapping[str, object], redacted_value)
        if entry.operation == "report.render" and requested_format == "pdf":
            if report_pdf_encoder is None:
                return _error(400, "unknown format 'pdf'")
            try:
                encoded = report_pdf_encoder.encode(redacted)
            except ReportPdfEncodingError:
                return _error(503, "report PDF encoding is unavailable")
            return Response(
                encoded,
                media_type=report_pdf_encoder.content_type,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{request.path_params["report_id"]}.pdf"'
                    )
                },
            )
        payload = _report_catalog_projection(
            redacted,
            operation=entry.operation,
            report_pdf_encoder=report_pdf_encoder,
        )
    except ProjectionUnavailableError:
        return _error(503, "authoritative projection is unavailable")
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(payload)


def _report_catalog_projection(
    payload: Mapping[str, object],
    *,
    operation: str,
    report_pdf_encoder: ReportPdfEncoder | None,
) -> Mapping[str, object]:
    if operation in {"report.list", "report.registry"}:
        formats = payload.get("formats")
        if not isinstance(formats, Sequence) or isinstance(formats, (str, bytes)):
            return payload
        names = [name for name in formats if isinstance(name, str) and name != "pdf"]
        if report_pdf_encoder is not None:
            names.append(report_pdf_encoder.name)
        return {**payload, "formats": names}
    if operation == "report.formats":
        items = payload.get("items")
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            return payload
        normalized = [
            item for item in items if not (isinstance(item, Mapping) and item.get("name") == "pdf")
        ]
        if report_pdf_encoder is not None:
            normalized.append(
                {
                    "name": report_pdf_encoder.name,
                    "content_type": report_pdf_encoder.content_type,
                }
            )
        return {**payload, "items": normalized}
    return payload


async def _proposal(
    request: Request,
    entry: OperationRoute,
    principal: OperatorPrincipal,
    writer: EventProposalWriter,
    replay_reader: DurableReplayReader,
) -> Response:
    body = await _json_body(request)
    if isinstance(body, Response):
        return body
    idempotency_key = request.headers.get("idempotency-key", "").strip()
    if not idempotency_key or len(idempotency_key) > 256:
        return _error(400, "Idempotency-Key MUST contain 1 to 256 characters")
    correlation_id = request.headers.get("x-correlation-id")
    if correlation_id is not None and len(correlation_id) > 256:
        return _error(400, "X-Correlation-ID MUST be at most 256 characters")
    try:
        receipt = await writer.propose(
            EventProposal(
                operation=entry.operation,
                principal_id=principal.subject_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload=body,
            )
        )
    except ProposalConflictError:
        return _error(409, "idempotency key conflicts with another proposal")
    if not receipt.durably_queued:
        return _error(503, "event proposal was not durably queued")
    if "text/event-stream" in request.headers.get("accept", "").lower():
        return await _stream(
            request,
            entry,
            principal,
            replay_reader,
            stream=f"read-investigation:{receipt.request_id}",
        )
    return JSONResponse(receipt.to_dict(), status_code=202)


async def _webhook(
    request: Request,
    entry: OperationRoute,
    writer: EventProposalWriter,
    verifier: WebhookVerifier,
) -> Response:
    raw = await _bounded_body(request)
    if raw is None:
        return _error(413, "body too large")
    if not await verifier.verify(entry.operation, dict(request.headers.items()), raw):
        return _error(401, "invalid webhook authentication")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return _error(400, "unparseable JSON body")
    if not isinstance(payload, dict):
        return _error(400, "body is not a JSON object")
    idempotency_key = request.headers.get("idempotency-key", "").strip()
    if not idempotency_key or len(idempotency_key) > 256:
        return _error(400, "Idempotency-Key MUST contain 1 to 256 characters")
    correlation_id = request.headers.get("x-correlation-id")
    if correlation_id is not None and len(correlation_id) > 256:
        return _error(400, "X-Correlation-ID MUST be at most 256 characters")
    try:
        receipt = await writer.propose(
            EventProposal(
                operation=entry.operation,
                principal_id=None,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                payload=payload,
            )
        )
    except ProposalConflictError:
        return _error(409, "idempotency key conflicts with another proposal")
    if not receipt.durably_queued:
        return _error(503, "event proposal was not durably queued")
    return JSONResponse({"accepted": True, **receipt.to_dict()}, status_code=202)


async def _stream(
    request: Request,
    entry: OperationRoute,
    principal: OperatorPrincipal,
    reader: DurableReplayReader,
    *,
    stream: str | None = None,
) -> Response:
    try:
        after_sequence = _last_event_id(request)
        batch = await reader.replay(
            ReplayQuery(
                stream=stream or entry.operation,
                principal_id=principal.subject_id,
                after_sequence=after_sequence,
                limit=MAX_LIMIT,
            )
        )
    except ProjectionUnavailableError:
        return _error(503, "authoritative stream is unavailable")
    except ValueError as exc:
        return _error(400, str(exc))

    async def events() -> AsyncIterator[bytes]:
        for event in batch.events:
            yield _sse_event(event)
        yield f"event: watermark\ndata: {json.dumps({'sequence': batch.watermark})}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _bounded_params(request: Request) -> dict[str, tuple[str, ...]]:
    keys = tuple(dict.fromkeys(request.query_params.keys()))
    if len(keys) > MAX_QUERY_VALUES:
        raise ValueError(f"query MUST contain at most {MAX_QUERY_VALUES} keys")
    params: dict[str, tuple[str, ...]] = {}
    for key in keys:
        if len(key) > 128:
            raise ValueError("query parameter name is too long")
        values = tuple(request.query_params.getlist(key))
        if len(values) > MAX_QUERY_VALUES or any(
            len(value) > MAX_QUERY_VALUE_CHARS for value in values
        ):
            raise ValueError(f"query parameter {key!r} exceeds its bound")
        params[key] = values
    return params


def _limit(params: Mapping[str, tuple[str, ...]]) -> int:
    raw = params.get("limit", (str(DEFAULT_LIMIT),))[-1]
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("limit MUST be an integer") from exc
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError(f"limit MUST be in [1, {MAX_LIMIT}]")
    return value


def _cursor(params: Mapping[str, tuple[str, ...]]) -> str | None:
    raw = params.get("cursor", (None,))[-1]
    if raw is not None and len(raw) > MAX_CURSOR_CHARS:
        raise ValueError(f"cursor MUST be at most {MAX_CURSOR_CHARS} characters")
    return raw


async def _json_body(request: Request) -> Mapping[str, object] | Response:
    raw = await _bounded_body(request)
    if raw is None:
        return _error(413, "body too large")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return _error(400, "unparseable JSON body")
    if not isinstance(body, dict):
        return _error(400, "body is not a JSON object")
    return body


async def _bounded_body(request: Request) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return None
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _last_event_id(request: Request) -> int | None:
    raw = request.headers.get("last-event-id")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("Last-Event-ID MUST be a non-negative integer") from exc
    if value < 0:
        raise ValueError("Last-Event-ID MUST be a non-negative integer")
    return value


def _sse_event(event: ReplayEvent) -> bytes:
    if _EVENT_NAME.fullmatch(event.event) is None:
        return _bounded_sse_frame(event.sequence, "invalid", {"error": "invalid_event_name"})
    return _bounded_sse_frame(event.sequence, event.event, redact_projection(event.data))


def _bounded_sse_frame(sequence: int, event: str, data: object) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    frame = f"id: {sequence}\nevent: {event}\ndata: {payload}\n\n".encode()
    if len(frame) <= MAX_SSE_FRAME_BYTES:
        return frame
    fallback = json.dumps({"error": "frame_too_large"}, separators=(",", ":"))
    return f"id: {sequence}\nevent: invalid\ndata: {fallback}\n\n".encode()


def _panel_entry(panel: PanelRoute) -> OperationRoute:
    return OperationRoute(
        path=panel.path,
        method="GET",
        name=f"panel:{panel.name}",
        operation=panel.operation,
        roles=panel.roles,
    )


def _validate_entries(entries: Sequence[OperationRoute]) -> None:
    identities = [(entry.method, entry.path) for entry in entries]
    if len(set(identities)) != len(identities):
        raise ValueError("operations routes MUST have unique method/path identities")
    for entry in entries:
        if not entry.path.startswith("/") or not entry.name or not entry.operation:
            raise ValueError("operations route path, name, and operation MUST be non-empty")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = ["PanelRoute", "build_operations_routes"]
