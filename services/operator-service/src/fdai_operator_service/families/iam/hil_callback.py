"""Signed HIL callback that records and enqueues decisions without execution."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionOutbox,
    HilDecisionOutboxRequest,
    HilDecisionRegistry,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import error_response, family_error

DEFAULT_MAX_SKEW_SECONDS: Final = 300
DEFAULT_MAX_BODY_BYTES: Final = 8 * 1024


@dataclass(frozen=True, slots=True)
class HilCallbackConfig:
    """HMAC and request ceilings supplied by the composition root."""

    secret: str
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("HilCallbackConfig.secret MUST be non-empty")
        if self.max_skew_seconds <= 0:
            raise ValueError("max_skew_seconds MUST be positive")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes MUST be positive")


@dataclass(frozen=True, slots=True)
class _CallbackBody:
    decision: HilApprovalDecision
    actor_oid: str
    justification: str
    actor_roles: tuple[OperatorRole, ...]


def make_hil_callback_route(
    *,
    registry: HilDecisionRegistry | None,
    outbox: HilDecisionOutbox | None,
    config: HilCallbackConfig | None,
    clock: Callable[[], datetime] | None = None,
) -> Route:
    """Build the URL-bound HMAC callback with durable decision replay."""
    now = clock or (lambda: datetime.now(UTC))

    async def handler(request: Request) -> Response:
        if registry is None or outbox is None or config is None:
            return error_response(503, "HIL callback dependencies are not configured")
        approval_id = str(request.path_params["approval_id"])
        if len(approval_id) > 128:
            return error_response(400, "approval_id is too long", kind="bad_request")
        try:
            payload = await _authenticate_and_parse(
                request=request,
                config=config,
                clock=now,
                approval_id=approval_id,
            )
        except _CallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        if not has_capability(payload.actor_roles, IamCapability.APPROVE_RUNTIME_HIL):
            return error_response(
                403,
                "approver lacks the approve-runtime-hil capability",
                kind="capability_forbidden",
            )

        try:
            receipt = await registry.get_decision_by_approval_id(approval_id)
            if receipt is not None:
                if (
                    receipt.decision is not payload.decision
                    or _normalize(receipt.approver_oid) != payload.actor_oid
                ):
                    return error_response(
                        409,
                        "approval was already resolved by a different decision or actor",
                        kind="already_resolved",
                    )
                receipt = replace(receipt, already_recorded=True)
            else:
                pending = await registry.get_pending_by_approval_id(approval_id)
                if pending is None:
                    return error_response(
                        404,
                        f"no pending HIL item for approval_id={approval_id!r}",
                        kind="not_found",
                    )
                if pending.submitter_oid and _normalize(pending.submitter_oid) == payload.actor_oid:
                    return error_response(
                        403,
                        "no_self_approval - actor_oid equals submitter_oid",
                        kind="self_approval_forbidden",
                    )
                if pending.metadata.get("decision_route") == "workflow" and not _meets_role(
                    payload.actor_roles,
                    pending.metadata.get("required_role", ""),
                ):
                    return error_response(
                        403,
                        "approver does not satisfy the workflow approval role",
                        kind="role_forbidden",
                    )
                receipt = await registry.record_decision(
                    HilDecisionCommand(
                        idempotency_key=pending.idempotency_key,
                        decision=payload.decision,
                        approver_oid=payload.actor_oid,
                        justification=payload.justification,
                        decided_at=now(),
                    )
                )
            if not receipt.delivered:
                try:
                    await outbox.enqueue(HilDecisionOutboxRequest(receipt=receipt))
                    receipt = await registry.mark_delivered(receipt)
                except Exception:  # noqa: BLE001 - recorded receipt remains replayable.
                    return error_response(
                        503,
                        "decision was recorded but delivery failed; retry the same decision",
                        kind="decision_publish_failed",
                    )
        except IamFamilyError as exc:
            return family_error(exc)

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

    return Route("/hil/{approval_id}/decision", handler, methods=["POST"])


class _CallbackError(RuntimeError):
    status_code = 400
    kind = "bad_request"


class _UnauthorizedCallbackError(_CallbackError):
    status_code = 401
    kind = "unauthorized"


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
        raise _UnauthorizedCallbackError("missing signature or timestamp header")
    _reject_replay(timestamp=timestamp, clock=clock, max_skew=config.max_skew_seconds)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > config.max_body_bytes:
                raise _CallbackError(
                    f"content-length {declared} exceeds max size ({config.max_body_bytes} bytes)"
                )
        except ValueError:
            pass
    raw = await request.body()
    if len(raw) > config.max_body_bytes:
        raise _CallbackError(f"body exceeds max size ({len(raw)} > {config.max_body_bytes} bytes)")
    if not signature.startswith("sha256="):
        raise _UnauthorizedCallbackError("signature MUST use sha256=<hex> shape")
    expected = compute_hmac(
        secret=config.secret,
        timestamp=timestamp,
        approval_id=approval_id,
        payload=raw,
    )
    if not hmac.compare_digest(expected, signature[len("sha256=") :]):
        raise _UnauthorizedCallbackError("HMAC signature mismatch")
    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise _CallbackError(f"invalid JSON body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise _CallbackError("body MUST be a JSON object")
    decision_raw = parsed.get("decision")
    if not isinstance(decision_raw, str):
        raise _CallbackError("'decision' MUST be a string (approve|reject)")
    try:
        decision = HilApprovalDecision(decision_raw.lower())
    except ValueError as exc:
        raise _CallbackError(f"unknown decision {decision_raw!r}") from exc
    actor_oid = parsed.get("actor_oid")
    if not isinstance(actor_oid, str) or not actor_oid.strip():
        raise _CallbackError("'actor_oid' MUST be a non-empty string")
    justification = parsed.get("justification", "")
    if not isinstance(justification, str):
        raise _CallbackError("'justification' MUST be a string")
    raw_roles = parsed.get("actor_roles", [])
    if not isinstance(raw_roles, list) or not all(isinstance(role, str) for role in raw_roles):
        raise _CallbackError("'actor_roles' MUST be a list of strings")
    roles: list[OperatorRole] = []
    for raw_role in raw_roles:
        try:
            roles.append(OperatorRole(raw_role))
        except ValueError:
            continue
    return _CallbackBody(
        decision=decision,
        actor_oid=_normalize(actor_oid),
        justification=justification,
        actor_roles=tuple(roles),
    )


def _reject_replay(*, timestamp: str, clock: Callable[[], datetime], max_skew: int) -> None:
    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        provided = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _UnauthorizedCallbackError(f"malformed timestamp: {exc}") from exc
    if provided.tzinfo is None:
        raise _UnauthorizedCallbackError("timestamp MUST carry a timezone offset")
    delta = abs((clock() - provided).total_seconds())
    if delta > max_skew:
        raise _UnauthorizedCallbackError(f"timestamp skew {delta:.0f}s exceeds max {max_skew}s")


def compute_hmac(*, secret: str, timestamp: str, approval_id: str, payload: bytes) -> str:
    """Sign timestamp, URL approval identity, and exact bytes in wire order."""
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(approval_id.encode())
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


def _meets_role(roles: tuple[OperatorRole, ...], required_role: str) -> bool:
    rank = {
        OperatorRole.READER: 0,
        OperatorRole.CONTRIBUTOR: 1,
        OperatorRole.APPROVER: 2,
        OperatorRole.OWNER: 3,
    }
    try:
        required = OperatorRole(required_role)
    except ValueError:
        return False
    if required not in rank:
        return False
    return any(rank.get(role, -1) >= rank[required] for role in roles)


def _normalize(value: str) -> str:
    return value.strip().casefold()


__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_SKEW_SECONDS",
    "HilCallbackConfig",
    "compute_hmac",
    "make_hil_callback_route",
]
