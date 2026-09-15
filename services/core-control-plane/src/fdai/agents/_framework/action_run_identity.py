"""Canonical identity shared by ActionRun authority messages.

The digest binds an approval or rollback to the exact ActionRun Thor will act
on. It is not authentication. The projection contains only lifecycle-stable
effect identity so it can be recomputed from a durable ActionRun snapshot.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

_DIGEST_PREFIX = "sha256:"
_IDENTITY_FIELDS = (
    "correlation_id",
    "action_id",
    "action_type",
    "resource_id",
    "action_idempotency_key",
    "params",
    "quorum_required",
    "initiator_principal",
    "rollback_contract",
    "verdict",
    "workflow_action",
)


class _StateReader(Protocol):
    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


def action_run_identity_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable wire projection used by every authority consumer."""

    action_idempotency_key = (
        value.get("action_idempotency_key")
        if "action_idempotency_key" in value
        else value.get("idempotency_key") or value.get("correlation_id", "")
    )
    projected = {
        "correlation_id": value.get("correlation_id", ""),
        "action_id": value.get("action_id"),
        "action_type": value.get("action_type", ""),
        "resource_id": value.get("resource_id"),
        "action_idempotency_key": action_idempotency_key,
        "params": value.get("params", {}),
        "quorum_required": value.get("quorum_required", 1),
        "initiator_principal": value.get("initiator_principal"),
        "rollback_contract": value.get("rollback_contract", "state_forward_only"),
        "verdict": value.get("verdict", ""),
        "workflow_action": value.get("workflow_action"),
    }
    try:
        encoded = json.dumps(
            projected,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        canonical = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("ActionRun identity MUST be canonical JSON") from exc
    if not isinstance(canonical, dict) or tuple(sorted(canonical)) != tuple(
        sorted(_IDENTITY_FIELDS)
    ):
        raise ValueError("ActionRun identity projection is malformed")
    return canonical


def action_run_identity_digest(value: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 identity for one ActionRun projection."""

    encoded = json.dumps(
        action_run_identity_projection(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def validate_action_run_identity(value: Mapping[str, Any]) -> str:
    """Return the computed identity and reject a conflicting supplied digest."""

    computed = action_run_identity_digest(value)
    supplied = value.get("action_run_identity")
    if supplied is not None and supplied != computed:
        raise ValueError("ActionRun identity digest does not match its payload")
    return computed


def is_action_run_identity(value: object) -> bool:
    """Return whether a value has the canonical ActionRun digest shape."""

    return (
        isinstance(value, str)
        and value.startswith(_DIGEST_PREFIX)
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def approval_matches_action_run(
    approval: Mapping[str, Any],
    action_run: Mapping[str, Any],
) -> bool:
    """Return whether an approval is bound to this exact ActionRun."""

    identity = approval.get("action_run_identity")
    return (
        is_action_run_identity(identity)
        and identity == action_run_identity_digest(action_run)
        and approval.get("action_type") == action_run.get("action_type")
        and approval.get("resource_id") == action_run.get("resource_id")
        and approval.get("action_idempotency_key") == action_run.get("idempotency_key")
        and approval.get("rollback_contract")
        == action_run.get("rollback_contract", "state_forward_only")
        and approval.get("action_id") == action_run.get("action_id")
    )


def rollback_matches_action_run(
    rollback: Mapping[str, Any],
    action_run: Mapping[str, Any],
) -> bool:
    """Return whether a rollback receipt is bound to this exact ActionRun."""

    identity = rollback.get("action_run_identity")
    return (
        is_action_run_identity(identity)
        and identity == action_run_identity_digest(action_run)
        and rollback.get("action_type") == action_run.get("action_type")
        and rollback.get("resource_id") == action_run.get("resource_id")
        and rollback.get("contract") == action_run.get("rollback_contract", "state_forward_only")
    )


def bounded_rollback_ref(value: object, *, max_length: int = 2_048) -> str | None:
    """Return a normalized rollback receipt or None when it is unusable."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= max_length else None


def validate_inactive_action_run_replay(
    current: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    """Suppress the same completed generation and reject correlation reuse."""

    if current.get("active") != "false":
        raise ValueError("ActionRun replacement requires an inactive tombstone")
    revision = current.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RuntimeError("Thor ActionRun revision is invalid")
    if current.get("correlation_id") != candidate.get("correlation_id"):
        raise RuntimeError("Thor ActionRun tombstone correlation conflicts")
    prior_idempotency = current.get("idempotency_key")
    next_idempotency = candidate.get("idempotency_key")
    if not isinstance(prior_idempotency, str) or not prior_idempotency:
        raise RuntimeError("legacy ActionRun tombstone cannot authorize correlation reuse")
    if prior_idempotency != next_idempotency:
        raise ValueError("ActionRun correlation cannot bind a different idempotency generation")


async def validate_durable_action_run_correlation(
    store: _StateReader,
    *,
    run_prefix: str,
    candidate: Mapping[str, Any],
) -> None:
    """Reject correlation reuse before a peer can claim an execution resource."""

    correlation_id = str(candidate.get("correlation_id") or "")
    current = await store.read_state(f"{run_prefix}{correlation_id}")
    if current is None:
        return
    if current.get("active") == "false":
        validate_inactive_action_run_replay(current, candidate)
        return
    if current.get("correlation_id") != correlation_id or current.get(
        "idempotency_key"
    ) != candidate.get("idempotency_key"):
        raise ValueError("active ActionRun correlation identity conflicts")


__all__ = [
    "approval_matches_action_run",
    "action_run_identity_digest",
    "action_run_identity_projection",
    "bounded_rollback_ref",
    "is_action_run_identity",
    "rollback_matches_action_run",
    "validate_durable_action_run_correlation",
    "validate_inactive_action_run_replay",
    "validate_action_run_identity",
]
