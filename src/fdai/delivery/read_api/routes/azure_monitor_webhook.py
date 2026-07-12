"""Azure Monitor alert webhook - push path #1 into the trust router.

Design contract: the fastest available detection path (~30-90 s
end-to-end) for a fork that stands up per-resource Azure Monitor
Metric Alert Rules. The rule's Action Group POSTs the Common Alert
Schema v2 payload to this route; the route normalizes it (via
:mod:`fdai.delivery.azure.monitor_alert`) and injects the resulting
:class:`~fdai.shared.contracts.models.Event` onto the ingest topic
through the injected :class:`~fdai.shared.providers.event_bus.EventBus`.

Kept parallel to :mod:`fdai.delivery.read_api.routes.webhook`
(generic HMAC-signed webhook) rather than folded into it because:

- **Auth is different.** Azure Monitor Action Groups do not sign the
  outbound POST with HMAC-SHA256. The standard hardening pattern is a
  shared bearer token in the ``Authorization`` header, or wrapping
  the URL behind APIM / Front Door / a Logic App that adds one. This
  route accepts the token via ``Authorization: Bearer <token>`` and
  compares it constant-time.
- **Body shape is fixed.** The Common Alert Schema is authoritative;
  the normalizer fail-closes on any deviation, so the route does not
  need a generic per-fork parser.
- **Publish key is the resource ref** (lowercased ARM id) so
  per-resource ordering matches every other Azure adapter (per-key
  partitioning on the ingest topic).

The route ships **disabled** upstream. Attach it in the composition
root ONLY when a fork enables the alert-webhook path:

    from fdai.delivery.read_api.routes.azure_monitor_webhook import (
        make_azure_monitor_webhook_route,
    )
    routes.append(make_azure_monitor_webhook_route(
        event_bus=container.event_bus,     # fork-wired
        topic=container.config.kafka.topic_events,
        bearer_token=os.environ["FDAI_AZURE_MONITOR_WEBHOOK_TOKEN"],
    ))

Safety
------

- HTTPS-only in production (upstream never provisions the route on an
  HTTP-only endpoint - the deploy sits behind Container Apps ingress
  which is HTTPS-by-default).
- Constant-time bearer compare (:func:`hmac.compare_digest`).
- Body cap (``max_body_bytes``) enforced before any parse.
- Malformed schema -> 400, wrong token -> 401, publish failure -> 502.
- Never executes a change - only injects an event; every autonomous
  action still goes through the standard trust router + risk gate.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.azure.monitor_alert import (
    NormalizerOptions,
    normalize_common_alert_schema,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

DEFAULT_AZURE_MONITOR_WEBHOOK_PATH: Final[str] = "/webhook/azure-monitor"
_DEFAULT_MAX_BODY_BYTES: Final[int] = 256 * 1024  # 256 KiB is well above CAS v2


def _error(status: int, reason: str) -> JSONResponse:
    return JSONResponse({"accepted": False, "reason": reason}, status_code=status)


async def _read_capped(request: Request, max_body: int) -> bytes | None:
    """Buffer the body with a hard cap so a chunked request cannot
    bypass the size limit by omitting Content-Length."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_bearer(header_value: str | None) -> str | None:
    """Return the token from a ``Bearer <token>`` header, else ``None``."""
    if not header_value:
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def make_azure_monitor_webhook_route(
    *,
    event_bus: EventBus,
    topic: str,
    bearer_token: str,
    path: str = DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
    default_mode: Mode = Mode.SHADOW,
) -> Route:
    """Return a Starlette POST route that accepts Azure Monitor alerts.

    ``bearer_token`` MUST be non-empty. A fork rotates it by re-deploying
    the composition root; the token is compared constant-time on every
    request and NEVER logged. The default response codes mirror the
    generic webhook route so a fork's ingress dashboards can reuse the
    same status conventions.
    """
    if not bearer_token:
        raise ValueError(
            "make_azure_monitor_webhook_route.bearer_token MUST be non-empty - "
            "the route rejects every request without a matching token"
        )
    if not topic:
        raise ValueError("make_azure_monitor_webhook_route.topic MUST be non-empty")
    if max_body_bytes <= 0:
        raise ValueError("make_azure_monitor_webhook_route.max_body_bytes MUST be positive")

    async def handler(request: Request) -> Response:
        # 1. Content-Length short-circuit (before any read).
        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    return _error(413, "body too large")
            except ValueError:
                pass  # non-numeric header -> fall through to the streaming cap

        # 2. Auth. Constant-time compare on the token.
        provided = _extract_bearer(request.headers.get("authorization"))
        if not provided or not hmac.compare_digest(provided, bearer_token):
            _LOGGER.warning("azure_monitor_webhook_unauthorized")
            return _error(401, "invalid or missing bearer token")

        # 3. Bounded body read.
        raw = await _read_capped(request, max_body_bytes)
        if raw is None:
            return _error(413, "body too large")

        # 4. Parse + normalize (fail-closed on any shape mismatch).
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return _error(400, "unparseable JSON body")
        if not isinstance(parsed, dict):
            return _error(400, "body is not a JSON object")

        try:
            event = normalize_common_alert_schema(
                parsed, options=NormalizerOptions(default_mode=default_mode)
            )
        except ValueError as exc:
            _LOGGER.info(
                "azure_monitor_webhook_rejected",
                extra={"reason": str(exc)},
            )
            return _error(400, f"schema rejected: {exc}")

        # 5. Publish. Per-key partitioning by the (lowercased) resource
        # ref so ordering across events for the same resource is stable
        # end-to-end (matches every other Azure adapter's convention).
        key = event.resource_ref or event.idempotency_key
        try:
            await event_bus.publish(topic, key, event.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - surface a clean rejection
            _LOGGER.warning(
                "azure_monitor_webhook_publish_failed",
                extra={"error": str(exc)},
            )
            return _error(502, "publish failed")

        _LOGGER.info(
            "azure_monitor_webhook_accepted",
            extra={
                "event_id": str(event.event_id),
                "resource_ref": event.resource_ref,
                "event_type": event.event_type,
            },
        )
        return JSONResponse(
            {
                "accepted": True,
                "event_id": str(event.event_id),
                "event_type": event.event_type,
            },
            status_code=202,
        )

    return Route(path, handler, methods=["POST"])


__all__ = [
    "DEFAULT_AZURE_MONITOR_WEBHOOK_PATH",
    "make_azure_monitor_webhook_route",
]
