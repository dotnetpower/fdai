"""Project durable Var approval state for one principal-scoped Process step."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast


class ProcessApprovalProjectionError(RuntimeError):
    """Durable approval state is missing, malformed, or inconsistent."""


def project_approval_requirements(
    approval: Mapping[str, object] | None,
    *,
    process_id: str,
    step_id: str,
    attempt: int,
    requester: str,
) -> dict[str, object]:
    """Return exact approval requirement and decision progress from Var state."""
    if approval is None:
        raise ProcessApprovalProjectionError("Durable approval state is unavailable")
    if (
        _text(approval, "process_id") != process_id
        or _text(approval, "step_id") != step_id
        or _integer(approval, "attempt", default=1) != attempt
        or _normalize(_text(approval, "requester_principal")) != _normalize(requester)
    ):
        raise ProcessApprovalProjectionError("Durable approval identity is inconsistent")
    role = _text(approval, "required_role")
    quorum = _integer(approval, "quorum")
    no_self_approval = _boolean(approval, "no_self_approval", default=True)
    timeout = _integer(approval, "timeout_seconds")
    approval_revision = _integer(approval, "revision")
    expires_at = _timestamp(approval.get("expires_at"), "approval expires_at")
    state = _text(approval, "state")
    claims = approval.get("decision_claims", {})
    if not isinstance(claims, Mapping):
        raise ProcessApprovalProjectionError("Durable approval decision claims are malformed")
    external = approval.get("_external_decisions", [])
    if not isinstance(external, list):
        raise ProcessApprovalProjectionError("External approval decisions are malformed")
    approved: set[str] = set()
    rejected = False
    for raw in [*claims.values(), *external]:
        decision = _mapping(raw, "approval decision")
        principal = _normalize(_text(decision, "principal"))
        result = _text(decision, "decision")
        if result in {"approve", "approved"}:
            if not (no_self_approval and principal == _normalize(requester)):
                approved.add(principal)
        elif result in {"reject", "rejected"}:
            rejected = True
        else:
            raise ProcessApprovalProjectionError("Durable approval decision is malformed")
    if state == "pending" and datetime.now(UTC) >= expires_at:
        state = "expired"
    if rejected:
        state = "rejected"
    return {
        "approval_role": role,
        "quorum": quorum,
        "no_self_approval": no_self_approval,
        "timeout_seconds": timeout,
        "approval_revision": approval_revision,
        "deadline_at": expires_at.isoformat(),
        "decision": state,
        "approved_count": len(approved),
        "remaining_quorum": max(0, quorum - len(approved)),
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProcessApprovalProjectionError(f"{label} is unavailable or malformed")
    return cast(Mapping[str, object], value)


def _text(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ProcessApprovalProjectionError(f"{key} is unavailable or malformed")
    return result


def _integer(
    value: Mapping[str, object],
    key: str,
    *,
    default: int | None = None,
) -> int:
    result = value.get(key, default)
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ProcessApprovalProjectionError(f"{key} is unavailable or malformed")
    return result


def _boolean(
    value: Mapping[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    result = value.get(key, default)
    if not isinstance(result, bool):
        raise ProcessApprovalProjectionError(f"{key} is unavailable or malformed")
    return result


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ProcessApprovalProjectionError(f"{label} is unavailable or malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProcessApprovalProjectionError(f"{label} is unavailable or malformed") from exc
    if parsed.tzinfo is None:
        raise ProcessApprovalProjectionError(f"{label} MUST include a timezone")
    return parsed.astimezone(UTC)


def _normalize(value: str) -> str:
    return value.strip().casefold()


__all__ = ["ProcessApprovalProjectionError", "project_approval_requirements"]
