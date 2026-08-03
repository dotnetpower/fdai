"""HIL callback POST endpoint - Wave W1.3.

The read-only console API remains **GET-only** by default; this module
adds one optional POST endpoint - ``POST /hil/{approval_id}/decision`` -
that a ChatOps push channel (Teams / Slack Adaptive Card) can call
back to record a decision. The route is only registered when a callback
config with an HMAC secret is supplied to :func:`build_app`; the default
composition has no POST surface at all
([app-shape.instructions.md](../../../../.github/instructions/app-shape.instructions.md)).

Security model
--------------

- **HMAC-authenticated**: caller signs the request as
  ``HMAC-SHA256(secret, f"{timestamp}.{approval_id}.{body}")`` and sends
  the digest in the ``X-FDAI-Signature: sha256=<hex>`` header alongside
  a ``X-FDAI-Timestamp``. Binding the URL path ``approval_id`` into the
  signed material prevents a captured valid message from being replayed
  against a different pending item (URL swap). The Teams push channel
  uses the exact same shape (see
  :mod:`fdai.delivery.chatops.teams_adapter`).
- **Replay window**: requests older than ``max_skew_seconds`` (default
  300s) are rejected with 401.
- **No self-approval**: the actor's oid on the body MUST differ from
  the pending item's ``submitter_oid``; a match returns 403.
- **Fail-closed idempotency**: the underlying
  :class:`~fdai.shared.providers.hil_registry.HilApprovalRegistry`
  is idempotent by ``idempotency_key`` (same decision -> returns prior
  receipt; conflicting decision -> 409).
- **Never bypasses dev-mode auth**: the HMAC path is orthogonal to the
  Bearer-token path used by GET routes. Same route can never accept
  both (POSTs are routed only to this handler).

The callback does NOT execute anything itself. It writes a durable
decision receipt, publishes that receipt to the typed decision transport,
and checkpoints delivery. A failed publish remains replayable by the same
signed actor and decision without restoring the item to the pending queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.hil_resume import HilResumeCoordinator, ResolveOutcome, ResolveResult
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.delivery.chatops.hil_decision import attempt_hil_decision_delivery
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilDecisionReceipt,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilRegistryError,
)

_LOGGER = logging.getLogger(__name__)


DEFAULT_MAX_SKEW_SECONDS: int = 300
DEFAULT_MAX_BODY_BYTES: int = 8 * 1024
DEFAULT_DECISION_PUBLISH_MAX_ATTEMPTS: int = 3
DEFAULT_DECISION_PUBLISH_TIMEOUT_SECONDS: float = 10.0
DEFAULT_DECISION_PUBLISH_RETRY_SECONDS: float = 0.1
DEFAULT_DECISION_DELIVERY_MAX_ATTEMPTS: int = 8
HilDecisionPublisher = Callable[[HilDecisionReceipt], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class HilCallbackConfig:
    """Composition-root configuration for the optional POST route.

    A ``None`` config on :func:`build_app` disables the route entirely.
    An explicit secret enables it; the deployer opts in.
    """

    secret: str
    """HMAC secret shared with the ChatOps push channel. Loaded from
    ``FDAI_CHATOPS_WEBHOOK_SECRET`` (or an equivalent) at
    composition time. MUST be non-empty."""

    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    """Reject requests whose ``X-FDAI-Timestamp`` is more than
    this many seconds away from ``now``. Defaults to 300s."""

    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    """Reject payloads larger than this. Cheap DoS ceiling."""

    decision_publish_max_attempts: int = DEFAULT_DECISION_PUBLISH_MAX_ATTEMPTS
    decision_publish_timeout_seconds: float = DEFAULT_DECISION_PUBLISH_TIMEOUT_SECONDS
    decision_publish_retry_seconds: float = DEFAULT_DECISION_PUBLISH_RETRY_SECONDS
    decision_delivery_max_attempts: int = DEFAULT_DECISION_DELIVERY_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("HilCallbackConfig.secret MUST be non-empty")
        if self.max_skew_seconds <= 0:
            raise ValueError("max_skew_seconds MUST be positive")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes MUST be positive")
        if self.decision_publish_max_attempts <= 0:
            raise ValueError("decision_publish_max_attempts MUST be positive")
        if self.decision_publish_timeout_seconds <= 0:
            raise ValueError("decision_publish_timeout_seconds MUST be positive")
        if self.decision_publish_retry_seconds < 0:
            raise ValueError("decision_publish_retry_seconds MUST be non-negative")
        if self.decision_delivery_max_attempts < self.decision_publish_max_attempts:
            raise ValueError(
                "decision_delivery_max_attempts MUST be >= decision_publish_max_attempts"
            )


class HilCallbackError(RuntimeError):
    """Base error surface for the callback handler.

    Each subclass carries an HTTP status the handler renders.
    """

    status_code: int = 500
    kind: str = "error"


class HilCallbackUnauthorizedError(HilCallbackError):
    status_code = 401
    kind = "unauthorized"


class HilCallbackBadRequestError(HilCallbackError):
    status_code = 400
    kind = "bad_request"


class HilCallbackForbiddenError(HilCallbackError):
    status_code = 403
    kind = "forbidden"


class HilCallbackConflictError(HilCallbackError):
    status_code = 409
    kind = "conflict"


class HilCallbackNotFoundError(HilCallbackError):
    status_code = 404
    kind = "not_found"


_DECISION_TO_CHANNEL: dict[HilApprovalDecision, HilDecision] = {
    HilApprovalDecision.APPROVE: HilDecision.APPROVE,
    HilApprovalDecision.REJECT: HilDecision.REJECT,
}


def _coordinator_response(approval_id: str, result: ResolveResult) -> Response:
    """Map a coordinator :class:`ResolveResult` onto the callback response.

    The coordinator has already audited the terminal decision; this only
    renders the HTTP status. Self-approval and conflicting-decision are
    the two refusals that carry a non-200 status (mirroring the registry
    path); every applied decision (executed / rejected / timeout /
    already-resolved / execute-failed) is a 200 with the outcome word so
    the caller can display it.
    """
    outcome = result.outcome
    if outcome is ResolveOutcome.SELF_APPROVAL_REFUSED:
        return _error(
            403,
            "self_approval_forbidden",
            "no_self_approval - approver equals the parked submitter",
        )
    if outcome is ResolveOutcome.MISSING_CAPABILITY:
        return _error(
            403,
            "capability_forbidden",
            "approver lacks the approve-runtime-hil capability",
        )
    if outcome is ResolveOutcome.CONFLICTING_DECISION:
        return _error(409, "already_resolved", result.reason or "conflicting decision")
    return JSONResponse(
        {
            "approval_id": approval_id,
            "outcome": outcome.value,
            "path": "coordinator",
            "delegated": result.delegated,
        },
        status_code=200,
    )


def make_hil_callback_route(
    *,
    registry: HilApprovalRegistry,
    config: HilCallbackConfig,
    coordinator: HilResumeCoordinator | None = None,
    decision_publisher: HilDecisionPublisher | None = None,
    now: Callable[[], datetime] | None = None,
) -> Route:
    """Return the single ``POST /hil/{approval_id}/decision`` Route.

    ``now`` is injectable so tests exercise the replay window without a
    time-travel dance. Defaults to timezone-aware UTC ``datetime.now``.
    """

    if decision_publisher is None:
        raise ValueError("decision_publisher MUST be configured for the HIL callback route")

    clock = now or _default_clock

    async def handler(request: Request) -> Response:
        approval_id = request.path_params["approval_id"]
        # Bound the input BEFORE the crypto path so an attacker cannot
        # amplify a 4xx path-param into a megabyte-scale error reply /
        # log line or force us to feed a huge string into the HMAC.
        # Real approval ids are UUIDs.
        if len(approval_id) > 128:
            return _error(400, "bad_request", "approval_id is too long")

        try:
            payload = await _authenticate_and_parse(
                request=request,
                config=config,
                clock=clock,
                approval_id=approval_id,
            )
        except HilCallbackError as exc:
            return _error(exc.status_code, exc.kind, str(exc))
        if not _approver_can_approve_hil(payload):
            return _error(
                403,
                "capability_forbidden",
                "approver lacks the approve-runtime-hil capability",
            )

        # Coordinator (park and resume) path takes precedence: an action
        # the control loop routed to HIL is parked in the StateStore, not
        # the registry. When a park exists for this approval_id the
        # coordinator applies the decision (APPROVE re-dispatches to the
        # executor, REJECT/records) and we return. A NOT_FOUND means no
        # park - fall through to the registry path below (console-pull
        # approvals raised via approve_hil).
        if coordinator is not None:
            resolve_result = await coordinator.resolve(
                approval_id=approval_id,
                decision=_DECISION_TO_CHANNEL[payload.decision],
                approver_oid=payload.actor_oid,
                reason=payload.justification,
                approver_can_approve_hil=_approver_can_approve_hil(payload),
            )
            if resolve_result.outcome is not ResolveOutcome.NOT_FOUND:
                return _coordinator_response(approval_id, resolve_result)

        receipt = await registry.get_decision_by_approval_id(approval_id)
        if receipt is not None:
            if (
                receipt.decision is not payload.decision
                or _normalize_oid(receipt.approver_oid) != payload.actor_oid
            ):
                return _error(
                    409,
                    "already_resolved",
                    "approval was already resolved by a different decision or actor",
                )
            receipt = replace(receipt, already_recorded=True)
        else:
            pending = await _find_pending_by_approval_id(registry, approval_id)
            if pending is None:
                return _error(
                    404,
                    "not_found",
                    f"no pending HIL item for approval_id={approval_id!r}",
                )

            if pending.submitter_oid and _normalize_oid(pending.submitter_oid) == payload.actor_oid:
                return _error(
                    403,
                    "self_approval_forbidden",
                    "no_self_approval - actor_oid equals submitter_oid",
                )

            try:
                receipt = await registry.record_decision(
                    idempotency_key=pending.idempotency_key,
                    decision=payload.decision,
                    approver_oid=payload.actor_oid,
                    justification=payload.justification,
                    decided_at=clock(),
                )
            except HilItemNotFoundError as exc:
                return _error(404, "not_found", str(exc))
            except HilItemAlreadyResolvedError as exc:
                return _error(409, "already_resolved", str(exc))
            except HilRegistryError as exc:
                return _error(500, "registry_error", str(exc))

        try:
            receipt = await _deliver_recorded_decision(
                registry=registry,
                publisher=decision_publisher,
                receipt=receipt,
                config=config,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - durable receipt remains replayable
            _LOGGER.exception(
                "hil_decision_publish_failed",
                extra={
                    "approval_id": receipt.approval_id or approval_id,
                    "idempotency_key": receipt.idempotency_key,
                },
            )
            return _error(
                503,
                "decision_publish_failed",
                "decision was recorded but delivery failed; retry the same decision",
            )

        _LOGGER.info(
            "hil_callback_recorded",
            extra={
                "approval_id": receipt.approval_id or approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "already_recorded": receipt.already_recorded,
            },
        )

        return JSONResponse(
            {
                "approval_id": receipt.approval_id or approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "already_recorded": receipt.already_recorded,
                "receipt_ref": receipt.receipt_ref,
                "decided_at": receipt.decided_at.astimezone(UTC).isoformat(),
                "delivered": receipt.delivered,
            }
        )

    return Route(
        "/hil/{approval_id}/decision",
        handler,
        methods=["POST"],
    )


# ---------------------------------------------------------------------------
# HMAC verification + body parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CallbackBody:
    decision: HilApprovalDecision
    actor_oid: str
    justification: str
    actor_roles: tuple[str, ...] = ()


def _approver_can_approve_hil(payload: _CallbackBody) -> bool:
    """Whether the approver holds ``Capability.APPROVE_RUNTIME_HIL``.

    The callback is HMAC-authenticated, so the push channel's asserted
    ``actor_roles`` are signed with the shared secret. Missing, unknown, or
    insufficient roles grant no approval authority.
    """
    resolved: set[Role] = set()
    for token in payload.actor_roles:
        try:
            resolved.add(Role(token))
        except ValueError:
            # An unknown role token grants nothing (fail closed on that token).
            continue
    return has_capability(resolved, Capability.APPROVE_RUNTIME_HIL)


async def _authenticate_and_parse(
    *,
    request: Request,
    config: HilCallbackConfig,
    clock: Callable[[], datetime],
    approval_id: str,
) -> _CallbackBody:
    signature = request.headers.get("x-fdai-signature", "")
    timestamp = request.headers.get("x-fdai-timestamp", "")
    if not signature or not timestamp:
        raise HilCallbackUnauthorizedError("missing signature or timestamp header")

    # Enforce replay window before spending crypto cycles.
    _reject_replay(timestamp=timestamp, clock=clock, max_skew=config.max_skew_seconds)

    # Reject oversize requests BEFORE buffering the body - checking
    # Content-Length up front prevents an attacker from forcing us to
    # read gigabytes into memory just to `len(raw)` after the fact. A
    # missing / non-numeric header falls through to the post-read check.
    declared_len = request.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) > config.max_body_bytes:
                raise HilCallbackBadRequestError(
                    f"content-length {declared_len} exceeds max size "
                    f"({config.max_body_bytes} bytes)"
                )
        except ValueError:
            pass

    raw = await request.body()
    if len(raw) > config.max_body_bytes:
        raise HilCallbackBadRequestError(
            f"body exceeds max size ({len(raw)} > {config.max_body_bytes} bytes)"
        )

    expected = _compute_hmac(
        secret=config.secret,
        timestamp=timestamp,
        approval_id=approval_id,
        payload=raw,
    )
    if not signature.startswith("sha256="):
        raise HilCallbackUnauthorizedError("signature MUST use sha256=<hex> shape")
    provided = signature[len("sha256=") :]
    if not hmac.compare_digest(expected, provided):
        raise HilCallbackUnauthorizedError("HMAC signature mismatch")

    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HilCallbackBadRequestError(f"invalid JSON body: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HilCallbackBadRequestError("body MUST be a JSON object")

    decision_raw = parsed.get("decision")
    if not isinstance(decision_raw, str):
        raise HilCallbackBadRequestError("'decision' MUST be a string (approve|reject)")
    try:
        decision = HilApprovalDecision(decision_raw.lower())
    except ValueError as exc:
        raise HilCallbackBadRequestError(f"unknown decision {decision_raw!r}") from exc

    actor_oid = parsed.get("actor_oid")
    if not isinstance(actor_oid, str) or not actor_oid.strip():
        raise HilCallbackBadRequestError("'actor_oid' MUST be a non-empty string")
    normalized_actor_oid = _normalize_oid(actor_oid)

    justification = parsed.get("justification", "")
    if not isinstance(justification, str):
        raise HilCallbackBadRequestError("'justification' MUST be a string")

    roles_raw = parsed.get("actor_roles", [])
    if not isinstance(roles_raw, list) or not all(isinstance(r, str) for r in roles_raw):
        raise HilCallbackBadRequestError("'actor_roles' MUST be a list of strings")

    return _CallbackBody(
        decision=decision,
        actor_oid=normalized_actor_oid,
        justification=justification,
        actor_roles=tuple(roles_raw),
    )


def _reject_replay(
    *,
    timestamp: str,
    clock: Callable[[], datetime],
    max_skew: int,
) -> None:
    """Raise :class:`HilCallbackUnauthorizedError` if outside the window."""

    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        provided = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HilCallbackUnauthorizedError(f"malformed timestamp: {exc}") from exc
    if provided.tzinfo is None:
        raise HilCallbackUnauthorizedError("timestamp MUST carry a timezone offset")
    now = clock()
    delta = abs((now - provided).total_seconds())
    if delta > max_skew:
        raise HilCallbackUnauthorizedError(f"timestamp skew {delta:.0f}s exceeds max {max_skew}s")


def _compute_hmac(*, secret: str, timestamp: str, approval_id: str, payload: bytes) -> str:
    """Sign the callback with the URL ``approval_id`` bound in.

    Binding ``approval_id`` prevents a captured valid callback message
    from being replayed against a different pending item by swapping the
    URL path. Wire format: ``HMAC-SHA256(secret, timestamp . approval_id . payload)``.
    """
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(approval_id.encode("utf-8"))
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


async def _find_pending_by_approval_id(registry: HilApprovalRegistry, approval_id: str) -> Any:
    """Locate one pending item by its authoritative approval identity."""

    return await registry.get_pending_by_approval_id(approval_id)


async def _deliver_recorded_decision(
    *,
    registry: HilApprovalRegistry,
    publisher: HilDecisionPublisher,
    receipt: HilDecisionReceipt,
    config: HilCallbackConfig,
) -> HilDecisionReceipt:
    if receipt.delivered:
        return receipt
    for attempt in range(config.decision_publish_max_attempts):
        receipt, delivered = await attempt_hil_decision_delivery(
            registry=registry,
            publisher=publisher,
            receipt=receipt,
            timeout_seconds=config.decision_publish_timeout_seconds,
            max_delivery_attempts=config.decision_delivery_max_attempts,
        )
        if delivered:
            return receipt
        if receipt.delivery_abandoned:
            break
        if attempt + 1 < config.decision_publish_max_attempts:
            await asyncio.sleep(config.decision_publish_retry_seconds * (2**attempt))
    raise RuntimeError(
        "HIL decision delivery did not complete "
        f"(attempts={receipt.delivery_attempts}, abandoned={receipt.delivery_abandoned})"
    )


def _normalize_oid(value: str) -> str:
    return value.strip().casefold()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _error(status: int, kind: str, message: str) -> JSONResponse:
    payload = {"error": {"status": status, "kind": kind, "message": message}}
    return JSONResponse(payload, status_code=status)


__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_SKEW_SECONDS",
    "HilCallbackBadRequestError",
    "HilCallbackConfig",
    "HilCallbackConflictError",
    "HilCallbackError",
    "HilCallbackForbiddenError",
    "HilCallbackNotFoundError",
    "HilCallbackUnauthorizedError",
    "make_hil_callback_route",
    "HilDecisionPublisher",
]
