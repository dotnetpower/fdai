"""Owner-only HTTP endpoint that queues one ordered poison-halt clear request."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.bus_poison_halt_clear import OrderedPoisonHaltClearService

_MAX_BODY_BYTES: Final = 16_384
_CLEAR_ROLES: Final = frozenset({OperatorRole.OWNER})


def make_ordered_poison_halt_clear_endpoint(
    service: OrderedPoisonHaltClearService | None,
    authenticator: OperatorAuthenticator,
) -> Callable[[Request], Awaitable[Response]]:
    """Return the Starlette endpoint; authentication errors propagate to app handlers."""

    async def post_ordered_poison_halt_clear(request: Request) -> Response:
        if service is None:
            return _error(503, "ordered poison halt clear is not configured")
        principal = authenticator.require_any(request.headers.get("authorization"), _CLEAR_ROLES)
        idempotency_key = request.headers.get("idempotency-key", "").strip()
        if not 1 <= len(idempotency_key) <= 256:
            return _error(400, "Idempotency-Key MUST contain 1 to 256 characters")
        raw_body = await request.body()
        if len(raw_body) > _MAX_BODY_BYTES:
            return _error(413, "ordered poison halt clear body is too large")
        try:
            raw = json.loads(raw_body)
        except (UnicodeDecodeError, ValueError):
            return _error(400, "invalid ordered poison halt clear request")
        if not isinstance(raw, Mapping):
            return _error(400, "invalid ordered poison halt clear request")
        try:
            accepted = await service.accept(
                principal=principal,
                idempotency_key=idempotency_key,
                body=raw,
            )
        except PermissionError:
            return _error(403, "ordered poison halt clear requires Owner")
        except RuntimeError as exc:
            return _error(503, str(exc))
        except ValueError:
            return _error(400, "invalid ordered poison halt clear request")
        return JSONResponse(
            {
                "submitted": accepted.accepted,
                "completed": False,
                "request_id": accepted.request_id,
                "dispatch_status": "queued",
                "topic": accepted.topic,
                "message": (
                    "Ordered poison halt clear request queued. The consumer resumes only "
                    "after Core verifies retained parked-record evidence and audits the clear."
                ),
            },
            status_code=202,
        )

    return post_ordered_poison_halt_clear


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = ["make_ordered_poison_halt_clear_endpoint"]
