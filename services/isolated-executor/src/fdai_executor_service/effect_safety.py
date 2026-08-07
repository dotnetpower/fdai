"""Pure safety checks and request rendering for Executor effects."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.direct_api import DirectApiRequest


class EffectCeilings(Protocol):
    """Hard effect limits supplied by service configuration."""

    @property
    def max_affected_resources(self) -> int: ...

    @property
    def max_rate_per_minute(self) -> int: ...


def missing_safety_invariant(action: Action) -> str | None:
    """Return the first missing executor safeguard, if any."""

    if not action.stop_condition.strip():
        return "action.stop_condition MUST NOT be empty (safety invariant 1)"
    if not action.rollback_ref.kind:
        return "action.rollback_ref.kind MUST be set (safety invariant 2)"
    if action.blast_radius is None:
        return "action.blast_radius MUST be set (safety invariant 3)"
    if not action.citing_rules:
        return "action.citing_rules MUST include at least one rule id"
    return None


def blast_radius_refusal(action: Action, ceilings: EffectCeilings) -> str | None:
    """Return why one action exceeds the service effect ceiling."""

    count = action.blast_radius.count
    if count is None:
        return "blast-radius count is undeclared"
    if count > ceilings.max_affected_resources:
        return f"blast-radius count {count} exceeds executor cap {ceilings.max_affected_resources}"
    rate = action.blast_radius.rate_per_minute
    if rate is not None and rate > ceilings.max_rate_per_minute:
        return (
            f"blast-radius rate {rate}/min exceeds executor cap {ceilings.max_rate_per_minute}/min"
        )
    return None


def build_direct_api_request(action: Action) -> DirectApiRequest:
    """Render one validated Action into the provider-neutral request."""

    rollback_ref = action.rollback_ref.kind.value
    if action.rollback_ref.reference:
        rollback_ref = f"{rollback_ref}:{action.rollback_ref.reference}"
    metadata = {
        "audit_ref": f"action:{action.action_id}",
        "stop_condition": action.stop_condition,
        "rollback_ref": rollback_ref,
        "max_resources": str(action.blast_radius.count or 1),
    }
    if action.executor_identity_ref is not None:
        metadata["executor_identity_ref"] = action.executor_identity_ref
    return DirectApiRequest(
        action_id=action.action_id,
        idempotency_key=action.idempotency_key,
        action_type_name=action.action_type,
        rule_ids=tuple(action.citing_rules),
        resource_ref=action.target_resource_ref,
        arguments=dict(action.params),
        labels=(("enforce",) if action.mode is Mode.ENFORCE else ("shadow",)),
        mode=action.mode,
        stop_conditions=tuple(action.stop_conditions),
        metadata=metadata,
    )


def action_fingerprint(action: Action) -> str:
    """Return the immutable payload identity used for conflict detection."""

    canonical = json.dumps(
        action.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def dedupe_key(action: Action) -> str:
    """Separate shadow and enforce attempts for the same source key."""

    return f"{action.idempotency_key}::{action.mode.value}"


def idempotency_lock_key(key: str) -> str:
    """Return the bounded lock identity for one idempotency key."""

    return f"fdai:idempotency:{hashlib.sha256(key.encode()).hexdigest()}"


def resource_lock_key(resource_ref: str) -> str:
    """Return the exact logical-target lock identity."""

    return f"fdai:resource:{resource_ref}"


__all__ = [
    "EffectCeilings",
    "action_fingerprint",
    "blast_radius_refusal",
    "build_direct_api_request",
    "dedupe_key",
    "idempotency_lock_key",
    "missing_safety_invariant",
    "resource_lock_key",
]
