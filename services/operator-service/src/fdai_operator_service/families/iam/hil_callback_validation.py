"""Bounded wire validation for HIL callback requests."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fdai_operator_service.families.iam.contracts import HilApprovalDecision
from fdai_operator_service.families.iam.hil_callback_authority import HilCallbackChannel
from starlette.requests import Request

_BODY_FIELDS: Final = frozenset(
    {
        "decision",
        "justification",
        "channel",
        "provider_actor_id",
        "audience",
        "correlation_id",
        "idempotency_key",
        "action_hash",
    }
)


@dataclass(frozen=True, slots=True)
class CallbackBody:
    """Authenticated callback fields before server-owned authority resolution."""

    decision: HilApprovalDecision
    justification: str
    channel: HilCallbackChannel
    provider_actor_id: str
    audience: str
    correlation_id: str
    idempotency_key: str
    action_hash: str
    signed_at: datetime


class CallbackError(RuntimeError):
    """A callback failed bounded request validation."""

    status_code = 400
    kind = "bad_request"


class UnauthorizedCallbackError(CallbackError):
    """A callback failed signature or replay validation."""

    status_code = 401
    kind = "unauthorized"


async def read_bounded_body(request: Request, maximum: int) -> bytes:
    """Read a callback body without exceeding the configured byte ceiling."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
            if declared_bytes < 0 or declared_bytes > maximum:
                raise CallbackError("callback body exceeds the configured limit")
        except ValueError as exc:
            raise CallbackError("content-length is invalid") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise CallbackError("callback body exceeds the configured limit")
    return bytes(body)


def authenticate_and_parse(
    *,
    request: Request,
    raw: bytes,
    secret: str,
    max_skew_seconds: int,
    clock: Callable[[], datetime],
    approval_id: str,
) -> CallbackBody:
    """Verify the HMAC and replay window, then parse the exact wire shape."""
    signature = request.headers.get("x-fdai-signature", "")
    timestamp = request.headers.get("x-fdai-timestamp", "")
    if not signature or not timestamp:
        raise UnauthorizedCallbackError("missing signature or timestamp header")
    signed_at = _reject_replay(timestamp=timestamp, clock=clock, max_skew=max_skew_seconds)
    if not signature.startswith("sha256="):
        raise UnauthorizedCallbackError("signature MUST use sha256=<hex> shape")
    expected = compute_hmac(
        secret=secret,
        timestamp=timestamp,
        approval_id=approval_id,
        payload=raw,
    )
    if not hmac.compare_digest(expected, signature[len("sha256=") :]):
        raise UnauthorizedCallbackError("HMAC signature mismatch")
    try:
        parsed = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CallbackError("callback body is invalid JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != _BODY_FIELDS:
        raise CallbackError("callback body fields do not match the contract")
    decision_raw = _text(parsed, "decision", maximum=16)
    try:
        decision = HilApprovalDecision(decision_raw.casefold())
    except ValueError as exc:
        raise CallbackError("callback decision MUST be approve or reject") from exc
    try:
        channel = HilCallbackChannel(_text(parsed, "channel", maximum=16).casefold())
    except ValueError as exc:
        raise CallbackError("callback channel MUST be teams or slack") from exc
    return CallbackBody(
        decision=decision,
        justification=_text(parsed, "justification", maximum=1_000),
        channel=channel,
        provider_actor_id=_text(parsed, "provider_actor_id", maximum=200),
        audience=_text(parsed, "audience", maximum=512),
        correlation_id=_text(parsed, "correlation_id", maximum=256),
        idempotency_key=_text(parsed, "idempotency_key", maximum=256),
        action_hash=_text(parsed, "action_hash", maximum=256),
        signed_at=signed_at,
    )


def body_hint(raw: bytes) -> dict[str, str]:
    """Extract only audit-safe routing hints from an untrusted body."""
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    provider_actor_id = value.get("provider_actor_id")
    if isinstance(provider_actor_id, str) and provider_actor_id.strip():
        result["provider_actor_id"] = provider_actor_id
    channel = value.get("channel")
    if isinstance(channel, str):
        normalized_channel = channel.strip().casefold()
        if normalized_channel in {item.value for item in HilCallbackChannel}:
            result["channel"] = normalized_channel
    return result


def callback_id(approval_id: str, timestamp: str, raw: bytes) -> str:
    """Derive a content-bound callback attempt identity."""
    digest = hashlib.sha256()
    digest.update(approval_id.encode())
    digest.update(b"\0")
    digest.update(timestamp.encode())
    digest.update(b"\0")
    digest.update(raw)
    return f"hil-callback:{digest.hexdigest()}"


def compute_hmac(*, secret: str, timestamp: str, approval_id: str, payload: bytes) -> str:
    """Sign timestamp, URL approval identity, and exact bytes in wire order."""
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(approval_id.encode())
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


def _reject_replay(
    *,
    timestamp: str,
    clock: Callable[[], datetime],
    max_skew: int,
) -> datetime:
    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        provided = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UnauthorizedCallbackError("callback timestamp is malformed") from exc
    if provided.tzinfo is None or provided.utcoffset() is None:
        raise UnauthorizedCallbackError("timestamp MUST carry a timezone offset")
    delta = abs((clock() - provided).total_seconds())
    if delta > max_skew:
        raise UnauthorizedCallbackError("callback timestamp is outside the replay window")
    return provided.astimezone(UTC)


def _text(value: Mapping[str, object], key: str, *, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item.strip()) > maximum:
        raise CallbackError(f"'{key}' MUST be bounded non-empty text")
    return item.strip()


__all__ = [
    "CallbackBody",
    "CallbackError",
    "UnauthorizedCallbackError",
    "authenticate_and_parse",
    "body_hint",
    "callback_id",
    "compute_hmac",
    "read_bounded_body",
]
