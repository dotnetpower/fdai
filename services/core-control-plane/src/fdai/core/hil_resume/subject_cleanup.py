"""Supersede duplicate pending approvals so each subject keeps one open request.

Before the subject index existed every repeated proposal parked a new approval. This planner
groups the pending requests by the same subject key the request path uses, keeps the newest one
open, links the older ones to it, and seeds the subject index so later observations land on the
survivor. Nothing is deleted: a superseded request keeps its record and gains an audit entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.hil_resume.approval_records import park_key
from fdai.core.hil_resume.subject_index import subject_key, subject_state_key
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.state_store import StateStore

SUPERSEDED_STATUS = "superseded_duplicate"
_PARK_PREFIX = "hil_park:"
_OPEN_STATUSES = ("pending", "awaiting_contact_consent")
_RECENT_EVENTS = 5


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """One subject with more than one open request."""

    subject_key: str
    survivor_id: str
    superseded_ids: tuple[str, ...]
    first_seen_at: str
    last_seen_at: str
    recent_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    """Read-only result of grouping the open requests."""

    open_total: int
    subject_total: int
    unrecognized: int
    groups: tuple[DuplicateGroup, ...]

    @property
    def superseded_total(self) -> int:
        return sum(len(group.superseded_ids) for group in self.groups)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Counts from applying a plan."""

    superseded: int
    skipped_changed: int
    subjects_seeded: int


async def plan_duplicate_cleanup(store: StateStore, *, page_size: int = 200) -> CleanupPlan:
    """Group every open request by subject without changing any state."""
    parks: list[Mapping[str, Any]] = []
    for status in _OPEN_STATUSES:
        offset, total = 0, 1
        while offset < total:
            page, total = await store.read_state_page(
                _PARK_PREFIX, limit=page_size, offset=offset, field="status", value=status
            )
            if not page:
                break
            parks.extend(page)
            offset += len(page)
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    unrecognized = 0
    for park in parks:
        key = _subject_of(park)
        if key is None:
            unrecognized += 1
            continue
        grouped.setdefault(key, []).append(park)
    groups = []
    for key, members in grouped.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=_age_key, reverse=True)
        groups.append(
            DuplicateGroup(
                subject_key=key,
                survivor_id=str(ordered[0]["approval_id"]),
                superseded_ids=tuple(str(item["approval_id"]) for item in ordered[1:]),
                first_seen_at=str(ordered[-1].get("parked_at") or ""),
                last_seen_at=str(ordered[0].get("parked_at") or ""),
                recent_event_ids=tuple(
                    str(_event_id(item)) for item in reversed(ordered[:_RECENT_EVENTS])
                ),
            )
        )
    return CleanupPlan(
        open_total=len(parks),
        subject_total=len(grouped),
        unrecognized=unrecognized,
        groups=tuple(sorted(groups, key=lambda group: group.subject_key)),
    )


async def apply_duplicate_cleanup(
    store: StateStore, plan: CleanupPlan, *, now: datetime
) -> CleanupResult:
    """Seed each subject index, then link and supersede its older duplicates."""
    superseded = skipped = seeded = 0
    for group in plan.groups:
        record = {
            "revision": 0,
            "subject_key": group.subject_key,
            "approval_id": group.survivor_id,
            "lineage": 1,
            "claimed_at": group.last_seen_at or now.isoformat(),
            "first_seen_at": group.first_seen_at or now.isoformat(),
            "last_seen_at": group.last_seen_at or now.isoformat(),
            "observed_count": len(group.superseded_ids) + 1,
            "recent_events": [
                {"event_id": event_id, "observed_at": group.last_seen_at}
                for event_id in group.recent_event_ids
            ],
            "lineage_refs": [],
        }
        if await store.write_state_if_absent(subject_state_key(group.subject_key), record):
            seeded += 1
        for approval_id in group.superseded_ids:
            if await _supersede(store, approval_id, group.survivor_id, now=now):
                superseded += 1
            else:
                skipped += 1
    return CleanupResult(superseded=superseded, skipped_changed=skipped, subjects_seeded=seeded)


async def _supersede(
    store: StateStore, approval_id: str, survivor_id: str, *, now: datetime
) -> bool:
    park = await store.read_state(park_key(approval_id))
    if park is None or park.get("status") not in _OPEN_STATUSES:
        return False
    revision = park.get("revision")
    expected = revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
    updated = dict(park)
    updated.update(
        {
            "status": SUPERSEDED_STATUS,
            "superseded_by": survivor_id,
            "superseded_at": now.isoformat(),
            "revision": expected + 1,
        }
    )
    return await store.compare_and_set_state_with_audit(
        park_key(approval_id),
        updated,
        expected_revision=expected,
        audit_entry={
            "actor": "fdai.core.hil_resume.subject_cleanup",
            "action_kind": "hil.request.superseded_duplicate",
            "mode": "shadow",
            "idempotency_key": f"{approval_id}:hil_superseded_duplicate",
            "approval_id": approval_id,
            "correlation_id": str(park.get("correlation_id") or approval_id),
            "recorded_at": now.isoformat(),
            "superseded_by": survivor_id,
        },
    )


def _subject_of(park: Mapping[str, Any]) -> str | None:
    """Rebuild the request-path subject key from a parked record, or ``None`` if unreadable."""
    try:
        action = Action.model_validate(park["action"])
        rule = Rule.model_validate(park["rule"])
        development = park.get("development_authority")
        policy = park.get("operator_policy")
        return subject_key(
            action=action,
            rule=rule,
            submitter_oid=str(park["submitter_oid"]),
            development_digest=(
                str(development["block_digest"]) if isinstance(development, Mapping) else None
            ),
            operator_policy_digest=(
                str(policy["policy_digest"]) if isinstance(policy, Mapping) else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _age_key(park: Mapping[str, Any]) -> tuple[str, str]:
    return str(park.get("parked_at") or ""), str(park.get("approval_id") or "")


def _event_id(park: Mapping[str, Any]) -> str:
    action = park.get("action")
    return str(action.get("event_id", "")) if isinstance(action, Mapping) else ""


__all__ = [
    "SUPERSEDED_STATUS",
    "CleanupPlan",
    "CleanupResult",
    "DuplicateGroup",
    "apply_duplicate_cleanup",
    "plan_duplicate_cleanup",
]
