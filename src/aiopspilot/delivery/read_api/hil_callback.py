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
  ``HMAC-SHA256(secret, f"{timestamp}.{body}")`` and sends the digest in
  the ``X-AIOpsPilot-Signature: sha256=<hex>`` header alongside a
  ``X-AIOpsPilot-Timestamp``. The Teams push channel uses the exact
  same shape (see
  :mod:`aiopspilot.delivery.chatops.teams_adapter`).
- **Replay window**: requests older than ``max_skew_seconds`` (default
  300s) are rejected with 401.
- **No self-approval**: the actor's oid on the body MUST differ from
  the pending item's ``submitter_oid``; a match returns 403.
- **Fail-closed idempotency**: the underlying
  :class:`~aiopspilot.shared.providers.hil_registry.HilApprovalRegistry`
  is idempotent by ``idempotency_key`` (same decision -> returns prior
  receipt; conflicting decision -> 409).
- **Never bypasses dev-mode auth**: the HMAC path is orthogonal to the
  Bearer-token path used by GET routes. Same route can never accept
  both (POSTs are routed only to this handler).

The callback does NOT execute anything itself - it merely writes the
decision into the registry. The executor observes the registry to
release the corresponding HIL-pending action; that path already exists.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from aiopspilot.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilRegistryError,
)

_LOGGER = logging.getLogger(__name__)


DEFAULT_MAX_SKEW_SECONDS: int = 300
DEFAULT_MAX_BODY_BYTES: int = 8 * 1024


@dataclass(frozen=True, slots=True)
class HilCallbackConfig:
    """Composition-root configuration for the optional POST route.

    A ``None`` config on :func:`build_app` disables the route entirely.
    An explicit secret enables it; the deployer opts in.
    """

    secret: str
    """HMAC secret shared with the ChatOps push channel. Loaded from
    ``AIOPSPILOT_CHATOPS_WEBHOOK_SECRET`` (or an equivalent) at
    composition time. MUST be non-empty."""

    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    """Reject requests whose ``X-AIOpsPilot-Timestamp`` is more than
    this many seconds away from ``now``. Defaults to 300s."""

    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    """Reject payloads larger than this. Cheap DoS ceiling."""

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("HilCallbackConfig.secret MUST be non-empty")
        if self.max_skew_seconds <= 0:
            raise ValueError("max_skew_seconds MUST be positive")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes MUST be positive")


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


def make_hil_callback_route(
    *,
    registry: HilApprovalRegistry,
    config: HilCallbackConfig,
    now: Callable[[], datetime] | None = None,
) -> Route:
    """Return the single ``POST /hil/{approval_id}/decision`` Route.

    ``now`` is injectable so tests exercise the replay window without a
    time-travel dance. Defaults to timezone-aware UTC ``datetime.now``.
    """

    clock = now or _default_clock

    async def handler(request: Request) -> Response:
        try:
            payload = await _authenticate_and_parse(
                request=request,
                config=config,
                clock=clock,
            )
        except HilCallbackError as exc:
            return _error(exc.status_code, exc.kind, str(exc))

        approval_id = request.path_params["approval_id"]

        # Load the pending item so we can enforce no_self_approval BEFORE
        # touching the registry write path.
        pending = await _find_pending_by_approval_id(registry, approval_id)
        if pending is None:
            return _error(404, "not_found", f"no pending HIL item for approval_id={approval_id!r}")

        if pending.submitter_oid and pending.submitter_oid == payload.actor_oid:
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


async def _authenticate_and_parse(
    *,
    request: Request,
    config: HilCallbackConfig,
    clock: Callable[[], datetime],
) -> _CallbackBody:
    signature = request.headers.get("x-aiopspilot-signature", "")
    timestamp = request.headers.get("x-aiopspilot-timestamp", "")
    if not signature or not timestamp:
        raise HilCallbackUnauthorizedError("missing signature or timestamp header")

    # Enforce replay window before spending crypto cycles.
    _reject_replay(timestamp=timestamp, clock=clock, max_skew=config.max_skew_seconds)

    raw = await request.body()
    if len(raw) > config.max_body_bytes:
        raise HilCallbackBadRequestError(
            f"body exceeds max size ({len(raw)} > {config.max_body_bytes} bytes)"
        )

    expected = _compute_hmac(secret=config.secret, timestamp=timestamp, payload=raw)
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
    if not isinstance(actor_oid, str) or not actor_oid:
        raise HilCallbackBadRequestError("'actor_oid' MUST be a non-empty string")

    justification = parsed.get("justification", "")
    if not isinstance(justification, str):
        raise HilCallbackBadRequestError("'justification' MUST be a string")

    return _CallbackBody(
        decision=decision,
        actor_oid=actor_oid,
        justification=justification,
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


def _compute_hmac(*, secret: str, timestamp: str, payload: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


async def _find_pending_by_approval_id(registry: HilApprovalRegistry, approval_id: str) -> Any:
    """Locate the pending item whose ``approval_id`` matches.

    The registry's read surface is keyed by ``idempotency_key``, so we
    scan the pending list. The list is Approver-bounded (`limit=50` by
    default) and typically small.
    """

    for item in await registry.list_pending(limit=200):
        if item.approval_id == approval_id:
            return item
    return None


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
]
