"""Content-free audit records for assignment lifecycle transitions."""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any

from fdai.core.human_assignment.model import AssignmentCase, AssignmentIntent, EffectKind


class AssignmentAuditKind(StrEnum):
    """Stable audit kinds emitted by assignment lifecycle writes."""

    REQUESTED = "human.assignment.requested"
    REVIEWED = "human.assignment.reviewed"
    TRANSITIONED = "human.assignment.transitioned"
    EFFECT_RECEIVED = "human.assignment.effect-received"
    ACTIVATED = "human.assignment.activated"
    DEGRADED = "human.assignment.degraded"
    SUPERSEDED = "human.assignment.superseded"


def build_assignment_audit(
    case: AssignmentCase,
    kind: AssignmentAuditKind,
    *,
    actor_ref: str,
    timestamp: str,
    effect_kind: EffectKind | None = None,
) -> dict[str, Any]:
    """Build a replayable audit record without human or provider content."""

    entry: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": case.case_id,
        "actor": _hashed_ref(actor_ref),
        "action_kind": kind.value,
        "tier": "T0",
        "mode": "shadow",
        "decision": case.state.value,
        "idempotency_key": _hashed_ref(case.intent.idempotency_key),
        "intent_digest": intent_digest(case.intent),
        "revision": case.revision,
        "rollback_reference": "forward-repair",
        "timestamp": timestamp,
    }
    if effect_kind is not None:
        entry["effect_kind"] = effect_kind.value
    return entry


def intent_digest(intent: AssignmentIntent) -> str:
    """Return a deterministic digest of immutable assignment intent."""

    canonical = json.dumps(intent.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hashed_ref(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.strip().casefold().encode()).hexdigest()}"


__all__ = ["AssignmentAuditKind", "build_assignment_audit", "intent_digest"]
