"""Webhook ingress POST route - mounts :class:`WebhookIngress` on an HTTP path.

The read-only console API stays **GET-only** by default; this module adds one
optional POST endpoint - ``POST /webhook`` - that fronts the transport-agnostic
:class:`~fdai.delivery.webhook.ingress.WebhookIngress`. The route is registered
only when a :class:`WebhookIngress` is supplied to :func:`build_app`
(``webhook_ingress`` config field); the default composition has no POST surface
([app-shape.instructions.md](../../../../.github/instructions/app-shape.instructions.md), P2-7).

Security model (delegated to :class:`WebhookIngress`)
----------------------------------------------------

- **HMAC-SHA256** over the raw body, verified constant-time; a missing / bad
  signature is rejected before the body is parsed.
- **Bounded body**: a ``Content-Length`` over the ingress cap is rejected up
  front (413) so a hostile sender cannot force a large read.
- **Fail-closed**: an unverified signature, oversized body, or unparseable JSON
  publishes nothing. The route never executes a change - it injects an event
  onto the ingest topic and the standard trust-router + risk-gate govern the
  rest.

The route maps :class:`~fdai.delivery.webhook.ingress.WebhookResult` onto HTTP
status: accepted -> ``202``, invalid signature -> ``401``, oversized body ->
``413``, unparseable / non-object body -> ``400``, publish failure -> ``502``.
"""

from __future__ import annotations

import logging
from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.webhook.ingress import WebhookIngress, WebhookResult

_LOGGER = logging.getLogger(__name__)

DEFAULT_WEBHOOK_PATH: Final[str] = "/webhook"

# WebhookResult.reason -> HTTP status. Anything unmapped falls back to 400.
_REASON_STATUS: Final[dict[str, int]] = {
    "invalid signature": 401,
    "body too large": 413,
    "unparseable JSON body": 400,
    "body is not a JSON object": 400,
    "publish failed": 502,
    "typed mapping rejected payload": 400,
}


def _status_for(result: WebhookResult) -> int:
    if result.accepted:
        return 202
    return _REASON_STATUS.get(result.reason, 400)


def make_webhook_route(
    *,
    ingress: WebhookIngress,
    path: str = DEFAULT_WEBHOOK_PATH,
) -> Route:
    """Return a Starlette ``POST`` route that fronts ``ingress``.

    The handler reads the raw body + headers and calls
    :meth:`WebhookIngress.handle`; the ingress performs all authentication
    and normalization. A ``Content-Length`` over the ingress body cap is
    rejected with 413 before the body is buffered.
    """
    max_body = ingress.max_body_bytes

    async def handler(request: Request) -> Response:
        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body:
                    return _error(413, "body too large")
            except ValueError:
                pass  # non-numeric header: fall through to the streaming cap

        # Stream the body with a hard cap so a chunked request that omits
        # Content-Length cannot bypass the size limit and exhaust memory -
        # a post-read length check would already have buffered the whole body.
        raw = await _read_capped(request, max_body)
        if raw is None:
            return _error(413, "body too large")

        headers = {k: v for k, v in request.headers.items()}
        result = await ingress.handle(headers=headers, body=raw)
        status = _status_for(result)

        if result.accepted:
            _LOGGER.info(
                "webhook_accepted",
                extra={
                    "event_id": result.event_id,
                    "idempotency_key": result.idempotency_key,
                },
            )
            return JSONResponse(
                {
                    "accepted": True,
                    "event_id": result.event_id,
                    "idempotency_key": result.idempotency_key,
                },
                status_code=status,
            )
        return _error(status, result.reason)

    return Route(path, handler, methods=["POST"])


def _error(status: int, reason: str) -> JSONResponse:
    return JSONResponse({"accepted": False, "reason": reason}, status_code=status)


async def _read_capped(request: Request, max_body: int) -> bytes | None:
    """Read the request body incrementally, aborting past ``max_body``.

    Returns the buffered bytes, or ``None`` when the stream exceeds the cap
    (the caller renders 413). Unlike ``request.body()``, this never buffers
    a body larger than the cap - the guard for a chunked request that omits
    ``Content-Length``.
    """
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["DEFAULT_WEBHOOK_PATH", "make_webhook_route"]
