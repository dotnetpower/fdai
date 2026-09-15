"""Canonical identity shared by ActionRun authority messages.

The digest binds an approval or rollback to the exact ActionRun Thor will act
on. It is not authentication. The projection contains only lifecycle-stable
effect identity so it can be recomputed from a durable ActionRun snapshot.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fdai.agents._framework.action_run_store_time import claim_lease_expiry

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


class _StateStore(Protocol):
    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...

    async def write_state_if_absent(self, key: str, value: dict[str, Any]) -> bool: ...


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


def action_fingerprint(value: Mapping[str, Any]) -> str:
    """Return the stable execution-effect fingerprint for one ActionRun."""

    payload = {
        name: value.get(name)
        for name in (
            "action_type",
            "resource_id",
            "idempotency_key",
            "params",
            "decision_case",
            "operational_context",
            "workflow_action",
            "kinetic_proposal",
        )
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _DIGEST_PREFIX + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def durable_action_run_state(
    candidate: Mapping[str, Any],
    *,
    active: bool,
    revision: int,
) -> dict[str, Any]:
    """Wrap an ActionRun payload with durable lifecycle metadata."""

    return {
        **dict(candidate),
        "action_run_identity": action_run_identity_digest(candidate),
        "active": "true" if active else "false",
        "revision": revision,
    }


def durable_action_run_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Remove persistence metadata from one durable ActionRun row."""

    return {
        name: item
        for name, item in value.items()
        if name not in {"active", "action_run_identity", "revision"}
    }


def validate_durable_action_run_state(
    current: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    """Accept only a durable row for the candidate's complete identity."""

    revision = current.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RuntimeError("Thor ActionRun revision is invalid")
    if current.get("correlation_id") != candidate.get("correlation_id"):
        raise RuntimeError("Thor ActionRun durable correlation conflicts")
    if current.get("active") not in {"pending", "true", "false"}:
        raise RuntimeError("Thor ActionRun durable activity marker is invalid")
    stored_identity = current.get("action_run_identity")
    if not is_action_run_identity(stored_identity):
        if current.get("active") == "true":
            stored_identity = action_run_identity_digest(current)
        elif (
            current.get("active") == "false"
            and isinstance(current.get("idempotency_key"), str)
            and current.get("idempotency_key")
            and current.get("idempotency_key") == candidate.get("idempotency_key")
        ):
            return
        else:
            raise RuntimeError("legacy ActionRun tombstone cannot authorize correlation reuse")
    if stored_identity != action_run_identity_digest(candidate):
        raise ValueError("ActionRun correlation cannot bind a different identity")


async def claim_durable_action_run_identity(
    store: _StateStore,
    *,
    run_key: str,
    completion_key: str,
    candidate: Mapping[str, Any],
    action_fingerprint: str,
) -> Literal["acquired", "existing", "completed", "contended"]:
    """Atomically claim one correlation before idempotency or resource state."""

    current = await store.read_state(run_key)
    if current is not None:
        validate_durable_action_run_state(current, candidate)
        return "existing"
    completion = await store.read_state(completion_key)
    if completion is not None and completion.get("status") == "completed":
        if (
            completion.get("resource_id") != candidate.get("resource_id")
            or completion.get("action_fingerprint") != action_fingerprint
        ):
            raise ValueError("completed idempotency identity conflicts with ActionRun")
        return "completed"
    if (
        completion is not None
        and completion.get("status") == "reserved"
        and claim_lease_expiry(completion) > datetime.now(tz=UTC)
    ):
        return "contended"
    if await store.write_state_if_absent(
        run_key,
        {
            **durable_action_run_state(candidate, active=True, revision=0),
            "active": "pending",
        },
    ):
        return "acquired"
    current = await store.read_state(run_key)
    if current is None:
        raise RuntimeError("Thor ActionRun correlation claim disappeared")
    validate_durable_action_run_state(current, candidate)
    return "existing"


async def load_durable_action_run_correlation(
    store: _StateStore,
    *,
    run_prefix: str,
    candidate: Mapping[str, Any],
) -> tuple[Literal["pending", "active", "completed"], dict[str, Any] | None]:
    """Load one exact active correlation without running recovery scans."""

    key = f"{run_prefix}{candidate.get('correlation_id', '')}"
    current = await store.read_state(key)
    if current is None:
        raise RuntimeError("Thor ActionRun correlation claim disappeared")
    validate_durable_action_run_state(current, candidate)
    status = current.get("active")
    if status == "false":
        return "completed", None
    return (
        "pending" if status == "pending" else "active",
        durable_action_run_payload(current),
    )


__all__ = [
    "approval_matches_action_run",
    "action_fingerprint",
    "action_run_identity_digest",
    "action_run_identity_projection",
    "bounded_rollback_ref",
    "claim_durable_action_run_identity",
    "durable_action_run_payload",
    "durable_action_run_state",
    "is_action_run_identity",
    "load_durable_action_run_correlation",
    "rollback_matches_action_run",
    "validate_action_run_identity",
    "validate_durable_action_run_state",
]
