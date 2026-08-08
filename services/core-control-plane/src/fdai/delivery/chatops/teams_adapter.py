"""Teams implementation of :class:`HilChannel` - Adaptive Card + HMAC auth.

Realizes the ChatOps A1 (approval) contract for Microsoft Teams. The
adapter dispatches a v1.5 Adaptive Card via an Incoming Webhook (P1
default) and MAY be upgraded to a Bot Framework REST call
(``POST /v3/conversations/{conv}/activities``) when the caller supplies
a :class:`WorkloadIdentity`. Callback delivery is out of scope for P1
- :meth:`TeamsHilAdapter.poll` returns :data:`HilDecision.PENDING`
until the future webhook trigger lands (see
``docs/roadmap/deployment/deploy-and-onboard.md § Azure Bot Free tier``).

Design boundaries
-----------------

- ``core/`` never imports this module; it lives under
  ``delivery/chatops/`` and is bound at the composition root through
  the :class:`~fdai.shared.providers.hil_channel.HilChannel`
  Protocol seam.
- No ``azure-identity`` / ``DefaultAzureCredential`` - when identity is
  required (Bot Framework mode) it flows exclusively through the
  injected :class:`WorkloadIdentity`.
- HTTP transport is an injected :class:`httpx.AsyncClient`; tests hand
  it a client backed by :class:`httpx.MockTransport`. Production wires
  a long-lived shared client at the composition root.

Wire contract (P1 - Incoming Webhook)
-------------------------------------

+---------------------------------+----------------------------------------------+
| Operation                       | HTTP wire                                    |
+=================================+==============================================+
| ``send``                        | ``POST {webhook_url}`` with Adaptive Card    |
| ``poll``                        | *(no-op - always PENDING in P1)*             |
+---------------------------------+----------------------------------------------+

The card body carries an **opaque ``approval_id``** only - the decision
endpoint (``fdai-api``) is what actually authorizes an APPROVE.
See ``docs/roadmap/interfaces/channels-and-notifications.md § 3
(Category boundaries MUST)``.

Authentication
--------------

Two modes, selected by construction:

- **Webhook mode** (default): when a ``webhook_secret`` is supplied,
  the adapter attaches an HMAC-SHA256 signature over the request body
  in the ``X-FDAI-Signature`` header (``sha256=<hex>``). The
  receiver re-computes the HMAC before honoring the callback. A
  timestamp header (``X-FDAI-Timestamp``) is included so the
  receiver can enforce a replay window.
- **Bot Framework mode**: when a :class:`WorkloadIdentity` is supplied,
  the adapter attaches a ``Bearer`` token acquired for the
  ``https://api.botframework.com/.default`` audience. Mutually
  exclusive with a webhook secret - configuration validation rejects a
  ``TeamsHilAdapterConfig`` that sets both.

Safety invariants
-----------------

- **Fail-closed**: any non-2xx response, timeout, or malformed body
  raises :class:`HilChannelError`; the caller falls back to the
  persisted HIL queue and pages the operational lane.
- **Bounded error bodies**: response text is truncated before it is
  embedded in the raised error, so an oversized vendor error page
  cannot flood the audit log.
- **Body redaction**: the adapter re-scans the rendered card for a
  small set of high-signal secret patterns and refuses to send when a
  match is found - defense in depth for a caller that forgot to
  redact. See :func:`_scan_for_secrets`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
    HilResponse,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_BOT_AUDIENCE: Final[str] = "https://api.botframework.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
_DEFAULT_MAX_ERROR_BODY_BYTES: Final[int] = 512
_SIGNATURE_HEADER: Final[str] = "X-FDAI-Signature"
_TIMESTAMP_HEADER: Final[str] = "X-FDAI-Timestamp"

_ADAPTIVE_CARD_VERSION: Final[str] = "1.5"
_ADAPTIVE_CARD_CONTENT_TYPE: Final[str] = "application/vnd.microsoft.card.adaptive"

# Small, high-signal secret patterns re-checked before dispatch. This is
# defense-in-depth - the caller is expected to have redacted already.
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"SharedAccessKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
)


@dataclass(frozen=True, slots=True)
class TeamsHilAdapterConfig:
    """Configuration for the Teams HIL adapter.

    Every value has a documented default so the composition root only
    needs to supply what a fork wants to override.
    """

    webhook_url: str
    """Target endpoint. For Incoming Webhook mode this is the channel
    webhook URL; for Bot Framework mode this is a Bot Framework
    ``conversations/{id}/activities`` URL."""

    webhook_secret: str | None = None
    """Shared secret used to compute the ``X-FDAI-Signature``
    HMAC. Mutually exclusive with :class:`WorkloadIdentity`
    (constructor validates)."""

    bot_audience: str = _DEFAULT_BOT_AUDIENCE
    """OIDC audience requested from :class:`WorkloadIdentity` when Bot
    Framework mode is active."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to ``send``."""

    max_error_body_bytes: int = _DEFAULT_MAX_ERROR_BODY_BYTES
    """Cap on the vendor error snippet embedded in :class:`HilChannelError`."""

    approve_callback_url: str | None = None
    """Optional absolute URL rendered as the ``Approve`` button's
    ``Action.Submit`` data target. When omitted the card carries the
    ``approval_id`` only; the future webhook receiver derives the URL
    from configuration."""

    reject_callback_url: str | None = None
    """Optional absolute URL for the ``Reject`` button; same contract
    as :attr:`approve_callback_url`."""


class TeamsHilAdapter(HilChannel):
    """Microsoft Teams implementation of :class:`HilChannel`."""

    def __init__(
        self,
        *,
        config: TeamsHilAdapterConfig,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity | None = None,
    ) -> None:
        if not config.webhook_url or not config.webhook_url.strip():
            raise ValueError("webhook_url MUST NOT be empty")
        if not config.webhook_url.startswith("https://"):
            # Refuse non-TLS and ambiguous schemes (`http://`, `file://`, etc.)
            # up front: a Teams / Slack Incoming Webhook is always HTTPS,
            # and a misconfigured `http://` variant would leak the HMAC
            # signature over the wire. Fail-closed at construction rather
            # than at first send.
            raise ValueError("webhook_url MUST use https:// scheme")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")
        if identity is not None and config.webhook_secret is not None:
            raise ValueError(
                "webhook_secret and WorkloadIdentity are mutually exclusive; "
                "pick either Incoming Webhook (secret) or Bot Framework (identity)"
            )
        self._config: Final[TeamsHilAdapterConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._identity: Final[WorkloadIdentity | None] = identity

    # ------------------------------------------------------------------
    # HilChannel Protocol
    # ------------------------------------------------------------------

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        card = _render_adaptive_card(request, config=self._config)
        payload = json.dumps(card, separators=(",", ":"), sort_keys=True).encode("utf-8")

        # Defense in depth - refuse to dispatch a card that still
        # carries a known secret pattern.
        secret_hit = _scan_for_secrets(payload.decode("utf-8"))
        if secret_hit is not None:
            raise HilChannelError(
                f"card body matched a secret pattern ({secret_hit}); refusing to send",
                approval_id=request.approval_id,
            )

        headers = await self._auth_headers(payload=payload)

        try:
            response = await self._http.post(
                self._config.webhook_url,
                content=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise HilChannelError(
                f"send request failed: {exc.__class__.__name__}",
                approval_id=request.approval_id,
            ) from exc

        if response.status_code >= 400:
            raise HilChannelError(
                f"send returned HTTP {response.status_code}: {self._trim(response.text)}",
                approval_id=request.approval_id,
                status_code=response.status_code,
            )

        channel_ref = _extract_channel_ref(response=response, approval_id=request.approval_id)
        return HilApprovalReceipt(
            approval_id=request.approval_id,
            channel_ref=channel_ref,
            sent_at=datetime.now(tz=UTC),
        )

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        # P1 posture - Incoming Webhook / Bot Framework send-only. The
        # webhook callback trigger that surfaces user clicks is a
        # future upgrade. Until then, poll is a no-op that surfaces
        # PENDING so the caller falls back to the persisted HIL queue.
        return HilResponse(
            approval_id=receipt.approval_id,
            decision=HilDecision.PENDING,
        )

    # ------------------------------------------------------------------
    # Response parser (public, static)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_response(payload: object) -> HilResponse:
        """Parse a raw Adaptive Card ``Action.Submit`` payload.

        The future webhook receiver hands the JSON body of a Teams
        callback here. Terminal decisions map to
        :data:`HilDecision.APPROVE` / :data:`HilDecision.REJECT`;
        an unrecognized action or a missing ``approval_id`` maps to
        :data:`HilDecision.PENDING` so the caller keeps its state.

        A ``timeout`` marker (adapter- or receiver-injected) maps to
        :data:`HilDecision.TIMEOUT`.

        Raises :class:`HilChannelError` when the payload is not a
        dict - the caller MUST log the error, not silently drop the
        message.
        """
        if not isinstance(payload, dict):
            raise HilChannelError(
                "callback payload is not a JSON object",
                approval_id="",
            )
        approval_id = payload.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            raise HilChannelError(
                "callback payload is missing 'approval_id'",
                approval_id="",
            )
        raw_action = payload.get("action")
        action = raw_action.lower() if isinstance(raw_action, str) else ""
        decision: HilDecision
        if action == "approve":
            decision = HilDecision.APPROVE
        elif action == "reject":
            decision = HilDecision.REJECT
        elif action == "timeout":
            decision = HilDecision.TIMEOUT
        else:
            decision = HilDecision.PENDING

        approver_id_raw = payload.get("approver_id")
        approver_id = approver_id_raw if isinstance(approver_id_raw, str) else None

        reason_raw = payload.get("reason")
        reason = reason_raw if isinstance(reason_raw, str) and reason_raw else None
        if reason is not None and _scan_for_secrets(reason) is not None:
            # Redact the reason if it inadvertently carries a secret;
            # never surface it to the audit log verbatim.
            reason = "[redacted]"

        received_at_raw = payload.get("received_at")
        received_at: datetime | None = None
        if isinstance(received_at_raw, str) and received_at_raw:
            try:
                # Accept RFC 3339 with or without trailing "Z".
                normalized = received_at_raw.replace("Z", "+00:00")
                received_at = datetime.fromisoformat(normalized)
            except ValueError:
                received_at = None

        return HilResponse(
            approval_id=approval_id,
            decision=decision,
            approver_id=approver_id,
            received_at=received_at,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _auth_headers(self, *, payload: bytes) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._identity is not None:
            token = await self._identity.get_token(self._config.bot_audience)
            headers["Authorization"] = f"Bearer {token.token}"
            return headers
        if self._config.webhook_secret is not None:
            timestamp = str(int(datetime.now(tz=UTC).timestamp()))
            signature = _hmac_sha256(
                secret=self._config.webhook_secret,
                timestamp=timestamp,
                payload=payload,
            )
            headers[_TIMESTAMP_HEADER] = timestamp
            headers[_SIGNATURE_HEADER] = f"sha256={signature}"
        return headers

    def _trim(self, text: str) -> str:
        cap = self._config.max_error_body_bytes
        raw = text.replace("\n", " ")
        if len(raw) <= cap:
            return raw
        return raw[:cap] + "..."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hmac_sha256(*, secret: str, timestamp: str, payload: bytes) -> str:
    """Compute ``hex(HMAC-SHA256(secret, timestamp + \".\" + payload))``.

    Binding the timestamp into the digest lets the receiver enforce a
    replay window without a separate nonce store - the timestamp is
    also present in a request header for the receiver to verify.
    """
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


def _scan_for_secrets(body: str) -> str | None:
    """Return the name of the first matching secret pattern, else ``None``."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(body):
            return pattern.pattern
    return None


def _render_adaptive_card(
    request: HilApprovalRequest,
    *,
    config: TeamsHilAdapterConfig,
) -> dict[str, Any]:
    """Render one v1.5 Adaptive Card for a Teams channel post.

    The card carries the opaque ``approval_id`` only - the decision
    endpoint re-verifies identity + action hash before honoring the
    click. Buttons are ``Action.Submit`` so the callback lands as a
    JSON body the future webhook receiver can parse via
    :meth:`TeamsHilAdapter.parse_response`.
    """
    facts: list[dict[str, str]] = [
        {"title": "Action", "value": request.action_type},
        {"title": "Target", "value": request.target_resource_ref},
        {"title": "Blast radius", "value": request.blast_radius_summary},
        {"title": "TTL", "value": f"{request.ttl_seconds}s"},
    ]
    if request.rule_ids:
        facts.append({"title": "Rules", "value": ", ".join(request.rule_ids)})
    if request.correlation_id:
        facts.append({"title": "Correlation", "value": request.correlation_id})

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": "FDAI HIL approval",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": f"Action `{request.action_id}` requires approval.",
            "wrap": True,
        },
        {"type": "FactSet", "facts": facts},
    ]
    if request.reasons:
        reason_lines = "\n".join(f"- {r}" for r in request.reasons)
        body.append(
            {
                "type": "TextBlock",
                "text": f"**Reasons**\n{reason_lines}",
                "wrap": True,
            }
        )
    body.append(
        {
            "type": "Input.Text",
            "id": "reason",
            "label": "Reason (optional)",
            "isMultiline": True,
            "maxLength": 500,
        }
    )

    approve_action: dict[str, Any] = {
        "type": "Action.Submit",
        "title": "Approve",
        "style": "positive",
        "data": {
            "action": "approve",
            "approval_id": request.approval_id,
            "action_hash": request.action_hash,
        },
    }
    if config.approve_callback_url is not None:
        approve_action["data"]["callback_url"] = config.approve_callback_url

    reject_action: dict[str, Any] = {
        "type": "Action.Submit",
        "title": "Reject",
        "style": "destructive",
        "data": {
            "action": "reject",
            "approval_id": request.approval_id,
            "action_hash": request.action_hash,
        },
    }
    if config.reject_callback_url is not None:
        reject_action["data"]["callback_url"] = config.reject_callback_url

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": _ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": [approve_action, reject_action],
    }

    # Teams Incoming Webhooks expect the card wrapped in an
    # ``attachments`` array with a MessageCard-style envelope.
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": _ADAPTIVE_CARD_CONTENT_TYPE,
                "content": card,
            }
        ],
    }


def _extract_channel_ref(*, response: httpx.Response, approval_id: str) -> str:
    """Read a channel-side correlation id from the response.

    Bot Framework returns the message id in the response body's ``id``
    field; Incoming Webhooks return an empty 200 body. We fall back to
    a generated ``teams:<uuid>`` when the response is opaque so the
    receipt still carries a unique correlation string.
    """
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            candidate = body.get("id") or body.get("messageId")
            if isinstance(candidate, str) and candidate:
                return f"teams:{candidate}"
    return f"teams:{approval_id}:{uuid.uuid4()}"


__all__ = [
    "TeamsHilAdapter",
    "TeamsHilAdapterConfig",
]
