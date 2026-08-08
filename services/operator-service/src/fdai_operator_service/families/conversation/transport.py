"""Bounded parsing, redaction, error, and SSE helpers for conversation routes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationResponse,
    JsonObject,
    JsonValue,
    PrincipalScope,
    StreamEvent,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MAX_QUERY_BYTES = 8_192
MAX_QUERY_VALUES = 64
MAX_PATH_VALUE_CHARS = 256
_CLIENT_SCOPE_KEYS = frozenset(
    {"owner_principal_id", "principal_id", "principal_scope", "reported_by", "user_id"}
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "connection_string",
        "cookie",
        "credential",
        "endpoint",
        "password",
        "secret",
        "token",
    }
)


async def read_json_body(request: Request, *, maximum: int) -> JsonObject:
    """Read one bounded JSON object and remove client-asserted identity fields."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > maximum:
                raise _bad_request(413, "request body exceeds cap")
        except ValueError:
            pass
    raw = await request.body()
    if len(raw) > maximum:
        raise _bad_request(413, "request body exceeds cap")
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _bad_request(400, "request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise _bad_request(400, "request body MUST be an object")
    return {
        str(key): _json_value(item)
        for key, item in value.items()
        if str(key) not in _CLIENT_SCOPE_KEYS
    }


def bounded_query(request: Request) -> JsonObject:
    """Return bounded query values without collapsing repeated parameters."""
    pairs = list(request.query_params.multi_items())
    if len(pairs) > MAX_QUERY_VALUES:
        raise _bad_request(400, f"query MUST contain at most {MAX_QUERY_VALUES} values")
    total = sum(len(key) + len(value) for key, value in pairs)
    if total > MAX_QUERY_BYTES:
        raise _bad_request(400, "query exceeds cap")
    grouped: dict[str, list[JsonValue]] = {}
    for key, value in pairs:
        if not key or len(key) > 64 or len(value) > 2_048:
            raise _bad_request(400, "query contains an unbounded value")
        grouped.setdefault(key, []).append(value)
    return {key: values[0] if len(values) == 1 else values for key, values in grouped.items()}


def bounded_path_params(request: Request) -> JsonObject:
    """Return bounded path parameters supplied by Starlette converters."""
    result: JsonObject = {}
    for key, value in request.path_params.items():
        if not isinstance(value, str) or not value or len(value) > MAX_PATH_VALUE_CHARS:
            raise _bad_request(400, f"{key} MUST be a bounded path value")
        result[key] = value
    return result


def idempotency_key(
    request: Request,
    *,
    operation: str,
    scope: PrincipalScope,
    body: JsonObject,
    query: JsonObject,
    path_params: JsonObject,
) -> str:
    """Use a bounded caller key or derive a stable digest over scoped intent."""
    supplied = request.headers.get("idempotency-key") or body.get("idempotency_key")
    if supplied is not None:
        if not isinstance(supplied, str) or not supplied.strip() or len(supplied) > 256:
            raise _bad_request(400, "idempotency_key MUST be a bounded string")
        return supplied.strip()
    material = json.dumps(
        {
            "body": body,
            "operation": operation,
            "path": path_params,
            "query": query,
            "subject_id": scope.subject_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


def last_event_id(request: Request) -> str | None:
    """Validate the SSE replay cursor without assuming numeric provider IDs."""
    value = request.headers.get("last-event-id")
    if value is None or value == "":
        return None
    if len(value) > 256 or "\r" in value or "\n" in value:
        raise _bad_request(400, "Last-Event-ID MUST be a bounded single-line value")
    return value


def response_from_contract(contract: ConversationResponse) -> Response:
    """Redact injected results and render their compatibility status and media type."""
    headers = dict(contract.headers)
    if contract.body is None:
        return Response(status_code=contract.status_code, headers=headers)
    if isinstance(contract.body, bytes):
        headers.setdefault("Cache-Control", "private, no-store")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        return Response(
            contract.body,
            status_code=contract.status_code,
            media_type=contract.media_type,
            headers=headers,
        )
    return JSONResponse(
        redact_object(contract.body),
        status_code=contract.status_code,
        headers=headers,
    )


def boundary_error_response(error: ConversationBoundaryError) -> JSONResponse:
    """Render a stable safe error envelope without exposing provider details."""
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message}},
        status_code=error.status_code,
    )


def unavailable_response(capability: str) -> JSONResponse:
    """Fail closed when a family dependency was not composed."""
    return JSONResponse(
        {
            "error": {
                "code": "unavailable",
                "message": f"{capability} is unavailable",
            }
        },
        status_code=503,
    )


def sse_frame(event: StreamEvent) -> bytes:
    """Encode one redacted replayable event using canonical SSE field order."""
    if event.event is None:
        return b": heartbeat\n\n"
    lines: list[str] = []
    if event.event_id is not None:
        lines.append(f"id: {event.event_id}")
    lines.append(f"event: {event.event}")
    if event.retry_ms is not None:
        lines.append(f"retry: {event.retry_ms}")
    payload = json.dumps(redact_object(event.data), separators=(",", ":"), sort_keys=True)
    lines.append(f"data: {payload}")
    return ("\n".join(lines) + "\n\n").encode()


def redact_object(value: Mapping[str, object]) -> JsonObject:
    """Remove credentials and deployment endpoints recursively from a response."""
    return {
        str(key): redact_value(item, depth=1)
        for key, item in value.items()
        if not _is_sensitive(str(key))
    }


def redact_value(value: object, *, depth: int) -> JsonValue:
    """Convert provider values to bounded JSON while applying recursive redaction."""
    if depth > 16:
        return "[redacted-depth]"
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): redact_value(item, depth=depth + 1)
            for key, item in value.items()
            if not _is_sensitive(str(key))
        }
    if isinstance(value, list | tuple):
        return [redact_value(item, depth=depth + 1) for item in value[:1_000]]
    return str(value)


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    raise _bad_request(400, "request body contains a non-JSON value")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or lowered.endswith(("_password", "_secret", "_token"))


def _bad_request(status_code: int, message: str) -> ConversationBoundaryError:
    code = "payload_too_large" if status_code == 413 else "invalid_request"
    return ConversationBoundaryError(status_code, code, message)


__all__ = [
    "boundary_error_response",
    "bounded_path_params",
    "bounded_query",
    "idempotency_key",
    "last_event_id",
    "read_json_body",
    "response_from_contract",
    "sse_frame",
    "unavailable_response",
]
