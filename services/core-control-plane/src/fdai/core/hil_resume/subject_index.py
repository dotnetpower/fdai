"""One open approval per subject, with a bounded observation summary and lineage history.

Every inventory generation proposes the same action again under a new event and idempotency key.
Without a subject index each proposal parks a new approval for the same human question. The
index maps one stable subject key to its current request, so a repeated proposal is recorded as
an observation instead of a second request. A parked request itself is never edited.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai.core.hil_resume.approval_records import approval_expired, park_key
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.state_store import StateStore

SUBJECT_PREFIX = "hil_subject:"
_OPEN_STATUSES = frozenset({"pending", "awaiting_contact_consent"})
_RECENT_EVENTS = 5
_LINEAGE_REFS = 20
# A claim whose park is not written yet is in flight for at most this long; after it the claim
# is stale and the next proposal may take it over. This is a crash-recovery bound, not a cooldown.
_CLAIM_WINDOW = timedelta(seconds=60)
_ATTEMPTS = 4


class SubjectAdmission(StrEnum):
    """What a proposal may do for its subject."""

    PARK = "park"
    """No usable request exists: park this one (first request or the next lineage revision)."""

    OPEN_REQUEST = "open_request"
    """A live request for the same subject exists: record an observation only."""

    REJECTED = "rejected"
    """The subject was rejected and its content is unchanged: stay closed."""


@dataclass(frozen=True, slots=True)
class SubjectAdmissionResult:
    """Admission outcome and the lineage the parked request must carry."""

    admission: SubjectAdmission
    approval_id: str
    lineage: int = 1
    previous_approval_id: str | None = None
    newly_suppressed: bool = False


def subject_key(
    *,
    action: Action,
    rule: Rule,
    submitter_oid: str,
    development_digest: str | None = None,
    operator_policy_digest: str | None = None,
) -> str:
    """Return the stable identity of the human question an approval answers.

    The key holds the action content and the authority context that bind a decision, and omits
    every per-event value (event id, action id, timestamps, idempotency key, correlation id), so
    a repeated observation of the same condition maps to the same subject while a changed
    action, rule, or authority context is a different subject.
    """
    payload = {
        "action_type": action.action_type,
        "target_resource_ref": action.target_resource_ref,
        "operation": str(action.operation),
        "params": action.params,
        "workflow_action": (
            action.workflow_action.model_dump(mode="json")
            if action.workflow_action is not None
            else None
        ),
        "rule": {"id": rule.id, "version": rule.version},
        "submitter_oid": submitter_oid.strip(),
        "development_digest": development_digest,
        "operator_policy_digest": operator_policy_digest,
    }
    canonical = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def subject_state_key(key: str) -> str:
    return f"{SUBJECT_PREFIX}{key}"


async def admit_subject(
    store: StateStore,
    *,
    key: str,
    candidate_approval_id: str,
    event_id: str,
    now: datetime,
) -> SubjectAdmissionResult:
    """Claim the subject for ``candidate_approval_id`` or report the request that owns it."""
    state_key = subject_state_key(key)
    for _ in range(_ATTEMPTS):
        record = await store.read_state(state_key)
        if record is None:
            created = await store.write_state_if_absent(
                state_key,
                _new_record(key, candidate_approval_id, event_id=event_id, now=now),
            )
            if created:
                return SubjectAdmissionResult(SubjectAdmission.PARK, candidate_approval_id)
            continue
        head_id = str(record.get("approval_id") or "")
        head = await store.read_state(park_key(head_id)) if head_id else None
        state = _head_state(record, head, now=now)
        if state == "open":
            await _observe(store, state_key, record, event_id=event_id, now=now)
            return SubjectAdmissionResult(
                SubjectAdmission.OPEN_REQUEST, head_id, lineage=_int(record, "lineage", 1)
            )
        if state == "rejected":
            newly = record.get("suppression_audited_for") != head_id
            await _observe(
                store,
                state_key,
                record,
                event_id=event_id,
                now=now,
                extra={"suppression_audited_for": head_id},
            )
            return SubjectAdmissionResult(
                SubjectAdmission.REJECTED,
                head_id,
                lineage=_int(record, "lineage", 1),
                newly_suppressed=newly,
            )
        reopened = _reopened_record(
            record,
            head,
            head_id=head_id,
            candidate_approval_id=candidate_approval_id,
            event_id=event_id,
            now=now,
        )
        if await store.compare_and_set_state(
            state_key, reopened, expected_revision=_int(record, "revision", 0)
        ):
            return SubjectAdmissionResult(
                SubjectAdmission.PARK,
                candidate_approval_id,
                lineage=int(reopened["lineage"]),
                previous_approval_id=head_id or None,
            )
    # Contention never creates a second request; the next proposal retries the admission.
    head_id = str((await store.read_state(state_key) or {}).get("approval_id") or "")
    return SubjectAdmissionResult(SubjectAdmission.OPEN_REQUEST, head_id)


def _head_state(record: Mapping[str, Any], head: Mapping[str, Any] | None, *, now: datetime) -> str:
    """Classify the subject's current request as open, rejected, or reusable."""
    if head is None:
        claimed_at = _parse(record.get("claimed_at"))
        in_flight = claimed_at is not None and now - claimed_at < _CLAIM_WINDOW
        return "open" if in_flight else "reusable"
    status = head.get("status")
    if status in _OPEN_STATUSES:
        return "reusable" if approval_expired(head, now=now) else "open"
    if status == "resolved" and head.get("decision") == "reject":
        return "rejected"
    return "reusable"


def _new_record(key: str, approval_id: str, *, event_id: str, now: datetime) -> dict[str, Any]:
    return {
        "revision": 0,
        "subject_key": key,
        "approval_id": approval_id,
        "lineage": 1,
        "claimed_at": now.isoformat(),
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "observed_count": 1,
        "recent_events": [{"event_id": event_id, "observed_at": now.isoformat()}],
        "lineage_refs": [],
    }


def _reopened_record(
    record: Mapping[str, Any],
    head: Mapping[str, Any] | None,
    *,
    head_id: str,
    candidate_approval_id: str,
    event_id: str,
    now: datetime,
) -> dict[str, Any]:
    refs = list(record.get("lineage_refs") or [])
    if head_id:
        refs.append(
            {
                "approval_id": head_id,
                "lineage": _int(record, "lineage", 1),
                "ended": _ended(head),
                "ended_at": (head or {}).get("resolved_at"),
            }
        )
    updated = _observed(record, event_id=event_id, now=now)
    updated.update(
        {
            "revision": _int(record, "revision", 0) + 1,
            "approval_id": candidate_approval_id,
            "lineage": _int(record, "lineage", 1) + 1,
            "claimed_at": now.isoformat(),
            "lineage_refs": refs[-_LINEAGE_REFS:],
        }
    )
    return updated


def _ended(head: Mapping[str, Any] | None) -> str:
    if head is None:
        return "never_parked"
    if head.get("status") == "resolved":
        return str(head.get("decision") or "resolved")
    return "expired"


async def _observe(
    store: StateStore,
    state_key: str,
    record: Mapping[str, Any],
    *,
    event_id: str,
    now: datetime,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Best-effort summary update; a lost race only skips one non-authoritative count."""
    updated = _observed(record, event_id=event_id, now=now)
    updated["revision"] = _int(record, "revision", 0) + 1
    if extra:
        updated.update(extra)
    await store.compare_and_set_state(
        state_key, updated, expected_revision=_int(record, "revision", 0)
    )


def _observed(record: Mapping[str, Any], *, event_id: str, now: datetime) -> dict[str, Any]:
    updated = dict(record)
    recent = list(record.get("recent_events") or [])
    recent.append({"event_id": event_id, "observed_at": now.isoformat()})
    updated["recent_events"] = recent[-_RECENT_EVENTS:]
    updated["observed_count"] = _int(record, "observed_count", 0) + 1
    updated["last_seen_at"] = now.isoformat()
    return updated


def _int(record: Mapping[str, Any], field: str, default: int) -> int:
    value = record.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _parse(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = [
    "SUBJECT_PREFIX",
    "SubjectAdmission",
    "SubjectAdmissionResult",
    "admit_subject",
    "subject_key",
    "subject_state_key",
]
