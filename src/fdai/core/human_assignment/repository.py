"""Atomic StateStore persistence for assignment case snapshots."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from fdai.core.human_assignment.audit import (
    AssignmentAuditKind,
    build_assignment_audit,
    intent_digest,
)
from fdai.core.human_assignment.coverage import normalize_principal_ref
from fdai.core.human_assignment.errors import AssignmentConflictError, AssignmentServiceError
from fdai.core.human_assignment.model import AssignmentCase, EffectKind
from fdai.core.human_assignment.transitions import (
    StaleAssignmentRevisionError,
    TransitionIntent,
    validate_transition,
)
from fdai.shared.providers.state_store import StateStore

_CASE_PREFIX: Final[str] = "human_assignment:case:"


def assignment_case_id(requester_ref: str, idempotency_key: str) -> str:
    """Derive the case id from normalized requester and idempotency identity."""

    identity = f"{normalize_principal_ref(requester_ref)}\x00{idempotency_key.strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"human-assignment:{identity}"))


async def create_case_state(
    store: StateStore,
    requested: AssignmentCase,
    *,
    actor_ref: str,
    at: datetime,
) -> AssignmentCase:
    """Atomically create and audit a draft, or replay matching intent."""

    state_key = _state_key(requested.case_id)
    existing = await store.read_state(state_key)
    if existing is not None:
        return _same_intent_or_conflict(existing, requested)
    created = await store.write_state_with_audit_if_absent(
        state_key,
        requested.to_dict(),
        build_assignment_audit(
            requested,
            AssignmentAuditKind.REQUESTED,
            actor_ref=actor_ref,
            timestamp=at.isoformat(),
        ),
    )
    if created:
        return requested
    raced = await store.read_state(state_key)
    if raced is None:
        raise RuntimeError("assignment case lost after an atomic create race")
    return _same_intent_or_conflict(raced, requested)


async def load_case_state(store: StateStore, case_id: str) -> AssignmentCase:
    """Load one durable assignment snapshot."""

    value = await store.read_state(_state_key(case_id.strip()))
    if value is None:
        raise AssignmentServiceError("assignment case was not found")
    return AssignmentCase.from_dict(dict(value))


async def persist_case_state(
    store: StateStore,
    current: AssignmentCase,
    candidate: AssignmentCase,
    *,
    expected_revision: int,
    audit_kind: AssignmentAuditKind,
    actor_ref: str,
    at: datetime,
    effect_kind: EffectKind | None = None,
) -> AssignmentCase:
    """Validate and atomically CAS one state snapshot with its audit record."""

    transition = TransitionIntent(expected_revision, candidate.state)
    validate_transition(current, candidate, transition)
    applied = await store.compare_and_set_state_with_audit(
        _state_key(current.case_id),
        candidate.to_dict(),
        expected_revision=expected_revision,
        audit_entry=build_assignment_audit(
            candidate,
            audit_kind,
            actor_ref=actor_ref,
            timestamp=at.isoformat(),
            effect_kind=effect_kind,
        ),
    )
    if applied:
        return candidate
    actual = await load_case_state(store, current.case_id)
    if actual == candidate:
        return actual
    raise StaleAssignmentRevisionError(
        f"stale assignment revision: expected={expected_revision}, current={actual.revision}"
    )


def _state_key(case_id: str) -> str:
    if not case_id:
        raise AssignmentServiceError("case_id MUST be non-empty")
    return f"{_CASE_PREFIX}{case_id}"


def _same_intent_or_conflict(
    stored: Mapping[str, Any],
    requested: AssignmentCase,
) -> AssignmentCase:
    current = AssignmentCase.from_dict(dict(stored))
    if intent_digest(current.intent) != intent_digest(requested.intent):
        raise AssignmentConflictError("idempotency key is bound to a different intent")
    return current


__all__ = [
    "assignment_case_id",
    "create_case_state",
    "load_case_state",
    "persist_case_state",
]
