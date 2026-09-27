"""Microsoft Bot Framework Direct Line custom-channel adapter (A2/A4 only).

FDAI acts as a Direct Line client that posts one bounded, read-only ``message``
activity into a deployment-owned conversation. The relay bot behind Direct Line
owns the custom channel that people read. The adapter keeps authentication and
transport inside this module, never receives an executor identity, and never
renders an approval, command, or conversation affordance.

A ``2xx`` response that carries an activity id is provider acceptance, not
publication: the receipt is ``accepted``, and only an independent publication
observation (:mod:`.receipt`) promotes the per-channel record to ``delivered``.
The pure activity renderer lives in :mod:`.direct_line_rendering` so rehearsal
and governed delivery produce identical activity bytes.

The Direct Line endpoint, conversation id, and credential are deployment values
that the composition root resolves from protected configuration. This module
never reads environment variables, and none of those values enter the rendered
activity, a receipt, or an error message.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import quote, urlsplit

import httpx

from fdai.shared.providers.notifications.base import (
    ChannelAmbiguousError,
    ChannelDeliveryError,
    ChannelKind,
    ChannelUnavailableError,
    DeliveryReceipt,
    NotificationMessage,
    TrustTier,
    require_channel_id,
)
from fdai.shared.providers.notifications.presentation import render_presentation

from .direct_line_rendering import (
    DIRECT_LINE_DEFAULT_SENDER_ID,
    render_direct_line_payload,
    require_direct_line_sender_id,
)

DIRECT_LINE_TRUST_TIERS: Final[frozenset[TrustTier]] = frozenset(
    {TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST}
)
"""The only tiers a Direct Line notification channel may carry.

A1 approvals and A3 conversations stay on their authenticated contracts; a
posted activity cannot verify an approver or carry an authenticated turn.
"""

ACTIVITY_DIGEST_PREFIX: Final[str] = "activity-sha256:"
"""Prefix of the value-free provider message id recorded for an accepted activity."""
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_MAX_ACKNOWLEDGEMENT_BYTES: Final[int] = 4 * 1024
_API_SUFFIX: Final[str] = "/v3/directline"
_NOT_RECEIVED: Final[dict[int, str]] = {
    400: "rejected the request",
    401: "rejected the client credential",
    403: "rejected the client credential",
    404: "rejected the request",
    429: "throttled the request",
}
"""Direct Line rejections that prove the relay bot never received the activity.

Direct Line reflects the relay bot's own outcome in the other non-``2xx``
statuses, for example ``502`` when the bot fails after it received the
activity, so those statuses stay ambiguous and are never resent blindly.
"""
_CONVERSATION_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_ACTIVITY_ID: Final = re.compile(r"^[\x21-\x7e]{1,256}$")
_CREDENTIAL: Final = re.compile(r"^[\x21-\x7e]{1,8192}$")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class DirectLineCredential:
    """One Direct Line bearer credential: a secret or a conversation-scoped token.

    ``expires_at`` is ``None`` for a secret, which does not expire, and the
    timezone-aware token expiry otherwise. ``value`` is excluded from ``repr``
    so the credential cannot leak into logs or audit text.
    """

    value: str = field(repr=False)
    expires_at: datetime | None = None


DirectLineCredentialProvider = Callable[[], Awaitable[DirectLineCredential]]
"""Async source of the current credential, owned by the composition root."""


def static_direct_line_credential(value: str) -> DirectLineCredentialProvider:
    """Wrap one resolved Direct Line secret as a credential provider.

    Raises :class:`ValueError` without echoing the value when it is empty or
    contains whitespace or control characters, so a malformed protected value
    fails startup instead of producing an unauthenticated request.
    """

    if _CREDENTIAL.fullmatch(value) is None:
        raise ValueError("Direct Line credential MUST be non-empty printable ASCII")
    credential = DirectLineCredential(value=value)

    async def provider() -> DirectLineCredential:
        return credential

    return provider


@dataclass(frozen=True, slots=True)
class DirectLineConfig:
    """Deployment-supplied binding for one Direct Line conversation.

    ``endpoint`` is the Direct Line API base URI for the bot's region or
    hosting model; an explicit ``/v3/directline`` suffix is accepted.
    ``endpoint`` and ``conversation_id`` are deployment values and stay out of
    ``repr``. There is no retry setting: the fan-out router's durable attempt
    ceiling is the only retry layer.
    """

    channel_id: str
    endpoint: str = field(repr=False)
    conversation_id: str = field(repr=False)
    trust_tiers: frozenset[TrustTier]
    sender_id: str = DIRECT_LINE_DEFAULT_SENDER_ID
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    credential_expiry_margin_seconds: float = 60.0


class DirectLineNotificationChannel:
    """Post an A2/A4 notification as one read-only Direct Line activity.

    Each ``send`` makes at most one request and never retries internally, so
    the fan-out router's durable attempt ceiling bounds the total requests per
    target. Failure classification is deterministic and fail-closed:

    - an expired, malformed, or unavailable credential raises before any
      request, so no unauthenticated activity is ever sent;
    - a connection failure raises :class:`ChannelUnavailableError`;
    - ``400``, ``401``, ``403``, ``404``, and ``429`` prove the relay bot never
      received the activity and raise a retryable :class:`ChannelDeliveryError`;
    - a lost response, a ``2xx`` without a valid activity id, and every other
      status, including the ``502`` and ``504`` that reflect the relay bot's
      own outcome, raise :class:`ChannelAmbiguousError` so nothing is resent
      blindly.
    """

    channel_kind: Final = ChannelKind.DIRECT_LINE

    def __init__(
        self,
        *,
        config: DirectLineConfig,
        http_client: httpx.AsyncClient,
        credential_provider: DirectLineCredentialProvider,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        require_channel_id(config.channel_id)
        if not config.trust_tiers or not config.trust_tiers <= DIRECT_LINE_TRUST_TIERS:
            raise ValueError(
                "Direct Line notification channels carry a2_operational_alert or a4_digest only"
            )
        if _CONVERSATION_ID.fullmatch(config.conversation_id) is None:
            raise ValueError(
                "Direct Line conversation_id MUST be 1-256 ASCII letters, digits, '.', '_', or '-'"
            )
        require_direct_line_sender_id(config.sender_id)
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.credential_expiry_margin_seconds < 0:
            raise ValueError("Direct Line credential expiry margin MUST be >= 0")
        self._config: Final = config
        self._activities_url: Final = (
            f"{_api_base(config.endpoint)}/conversations/"
            f"{quote(config.conversation_id, safe='')}/activities"
        )
        self._http: Final = http_client
        self._credential_provider: Final = credential_provider
        self._clock: Final = clock

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def trust_tiers(self) -> frozenset[TrustTier]:
        return self._config.trust_tiers

    async def send(self, message: NotificationMessage) -> DeliveryReceipt:
        """Render, authenticate, and post one activity; return provider acceptance."""

        if message.trust_tier not in self._config.trust_tiers:
            raise ChannelDeliveryError(
                f"Direct Line channel does not carry trust tier {message.trust_tier.value}"
            )
        payload = render_direct_line_payload(
            render_presentation(message, channel_id=self.channel_id),
            sender_id=self._config.sender_id,
        )
        credential = await self._current_credential()
        response = await self._post_once(
            payload.body,
            {
                "Authorization": f"Bearer {credential.value}",
                "Content-Type": payload.content_type,
            },
        )
        return DeliveryReceipt(
            channel_kind=ChannelKind.DIRECT_LINE,
            channel_id=self._config.channel_id,
            delivered=False,
            accepted=True,
            provider_message_id=_accepted_activity_id(response),
        )

    async def _current_credential(self) -> DirectLineCredential:
        """Return a usable credential or fail closed before any transport."""

        try:
            credential = await self._credential_provider()
        except Exception as exc:
            raise ChannelUnavailableError(
                f"Direct Line credential provider failed: {type(exc).__name__}"
            ) from exc
        if _CREDENTIAL.fullmatch(credential.value) is None:
            raise ChannelDeliveryError("Direct Line credential is missing or malformed")
        expires_at = credential.expires_at
        if expires_at is None:
            return credential
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ChannelDeliveryError("Direct Line credential expiry MUST be timezone-aware")
        margin = timedelta(seconds=self._config.credential_expiry_margin_seconds)
        if expires_at - margin <= self._clock():
            raise ChannelDeliveryError("Direct Line credential is expired or inside its margin")
        return credential

    async def _post_once(self, payload: bytes, headers: dict[str, str]) -> httpx.Response:
        """Send exactly one request and classify every non-``2xx`` outcome."""

        try:
            response = await self._http.post(
                self._activities_url,
                content=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ChannelUnavailableError(
                f"Direct Line connection failed: {type(exc).__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ChannelAmbiguousError(
                f"Direct Line acknowledgement was not observed: {type(exc).__name__}"
            ) from exc

        status = response.status_code
        if 200 <= status < 300:
            return response
        reason = _NOT_RECEIVED.get(status)
        if reason is not None:
            raise ChannelDeliveryError(f"Direct Line {reason} with HTTP {status}")
        raise ChannelAmbiguousError(
            f"Direct Line returned HTTP {status}; the relay bot may already have the activity"
        )


def _api_base(endpoint: str) -> str:
    """Return the validated ``.../v3/directline`` base without echoing the value."""

    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Direct Line endpoint MUST be an absolute https URL") from exc
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(character.isspace() for character in endpoint)
    ):
        raise ValueError(
            "Direct Line endpoint MUST be an absolute https URL without credentials, "
            "query, or fragment"
        )
    hostname = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    host = hostname if port is None else f"{hostname}:{port}"
    path = parts.path.rstrip("/")
    if not path.endswith(_API_SUFFIX):
        path = f"{path}{_API_SUFFIX}"
    return f"https://{host}{path}"


def _accepted_activity_id(response: httpx.Response) -> str:
    """Return a value-free handle for the provider activity id, or classify ambiguity.

    Direct Line activity ids embed the conversation id, a deployment value, so
    the receipt carries only the SHA-256 digest; a relay that knows the raw id
    can compute the same digest to correlate a publication receipt.
    """

    if len(response.content) > _MAX_ACKNOWLEDGEMENT_BYTES:
        raise ChannelAmbiguousError("Direct Line acknowledgement exceeds the bounded size")
    try:
        body = json.loads(response.content)
    except ValueError as exc:
        raise ChannelAmbiguousError("Direct Line acknowledgement is not valid JSON") from exc
    activity_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(activity_id, str) or _ACTIVITY_ID.fullmatch(activity_id) is None:
        raise ChannelAmbiguousError("Direct Line acknowledgement carried no valid activity id")
    return f"{ACTIVITY_DIGEST_PREFIX}{hashlib.sha256(activity_id.encode()).hexdigest()}"


__all__ = [
    "ACTIVITY_DIGEST_PREFIX",
    "DIRECT_LINE_TRUST_TIERS",
    "DirectLineConfig",
    "DirectLineCredential",
    "DirectLineCredentialProvider",
    "DirectLineNotificationChannel",
    "static_direct_line_credential",
]
