"""Atomic persistence for human reporting-line cases."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from fdai.core.human_reporting.model import (
    ReportingLineCase,
    ReportingLineModelError,
    normalize_principal,
)
from fdai.shared.providers.state_store import StateStore

CASE_PREFIX: Final = "human_reporting:case:"


def reporting_line_case_id(upload_id: str, candidate_id: str) -> str:
    """Derive one stable case id from the immutable document candidate."""

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"human-reporting:{upload_id}:{candidate_id}"))


async def create_case_state(
    store: StateStore,
    requested: ReportingLineCase,
    *,
    actor_ref: str,
    at: datetime,
) -> ReportingLineCase:
    """Create one case with audit, or return its exact idempotent replay."""

    key = CASE_PREFIX + requested.case_id
    existing = await store.read_state(key)
    if existing is not None:
        return _same_case(existing, requested)
    created = await store.write_state_with_audit_if_absent(
        key,
        requested.to_dict(),
        _audit(requested, actor_ref=actor_ref, at=at, action_kind="human.reporting.requested"),
    )
    if created:
        return requested
    raced = await store.read_state(key)
    if raced is None:
        raise RuntimeError("reporting-line case disappeared after create race")
    return _same_case(raced, requested)


async def load_case_state(store: StateStore, case_id: str) -> ReportingLineCase:
    """Load one exact reporting-line case."""

    value = await store.read_state(CASE_PREFIX + case_id)
    if value is None:
        raise ReportingLineModelError("reporting-line case was not found")
    return ReportingLineCase.from_dict(dict(value))


async def list_case_states(
    store: StateStore,
    *,
    limit: int = 5_000,
) -> tuple[ReportingLineCase, ...]:
    """Read the bounded reporting-line case set used to build the current graph."""

    if isinstance(limit, bool) or not 1 <= limit <= 5_000:
        raise ReportingLineModelError("reporting-line case limit MUST be in [1, 5000]")
    values = await store.read_states(CASE_PREFIX, limit=limit + 1)
    if len(values) > limit:
        raise ReportingLineModelError("reporting-line case coverage is incomplete")
    return tuple(ReportingLineCase.from_dict(dict(value)) for value in values)


async def persist_case_state(
    store: StateStore,
    current: ReportingLineCase,
    candidate: ReportingLineCase,
    *,
    actor_ref: str,
    action_kind: str,
    at: datetime,
) -> ReportingLineCase:
    """CAS one validated transition with its content-free audit entry."""

    if candidate.case_id != current.case_id or candidate.revision != current.revision + 1:
        raise ReportingLineModelError("reporting-line transition identity or revision is invalid")
    applied = await store.compare_and_set_state_with_audit(
        CASE_PREFIX + current.case_id,
        candidate.to_dict(),
        expected_revision=current.revision,
        audit_entry=_audit(candidate, actor_ref=actor_ref, at=at, action_kind=action_kind),
    )
    if applied:
        return candidate
    actual = await load_case_state(store, current.case_id)
    if actual == candidate:
        return actual
    raise ReportingLineModelError("reporting-line case revision is stale")


def _same_case(
    stored: Mapping[str, Any],
    requested: ReportingLineCase,
) -> ReportingLineCase:
    current = ReportingLineCase.from_dict(dict(stored))
    if (
        current.edge_digest != requested.edge_digest
        or current.requester_ref != requested.requester_ref
    ):
        raise ReportingLineModelError("reporting-line idempotency key is bound to another edge")
    return current


def _audit(
    case: ReportingLineCase,
    *,
    actor_ref: str,
    at: datetime,
    action_kind: str,
) -> dict[str, object]:
    return {
        "actor": normalize_principal(actor_ref),
        "action_kind": action_kind,
        "case_id": case.case_id,
        "edge_digest": case.edge_digest,
        "state": case.state.value,
        "revision": case.revision,
        "recorded_at": at.isoformat(),
        "mode": "shadow",
        "execution_authority": False,
        "approval_authority": False,
    }


__all__ = [
    "CASE_PREFIX",
    "create_case_state",
    "list_case_states",
    "load_case_state",
    "persist_case_state",
    "reporting_line_case_id",
]
