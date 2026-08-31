"""Server-authored Kubernetes Pod lifecycle section of `/detection-readiness`.

The control plane reduces Pod detection records and persists one projection per
target. The Operator Service does not re-derive that reduction - it is not the
component that observed the evidence, so a second opinion here would be a
second, weaker conclusion.

What this module owns is the boundary check. A tracked row is admitted only
when it carries the schema version, the four separated answers, and a fixed
absence of cause and authority claims. Anything else makes the section
``unavailable`` with a named reason, because a Console that silently drops a
malformed target would report a shorter, calmer failure history than the one
the control plane actually retained.

The readiness section is unaffected by an unavailable lifecycle section: they
answer different questions and a defect in one is not evidence about the other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, cast

from fdai_service_contracts import JsonObject, JsonValue

LIFECYCLE_SCHEMA_VERSION: Final = 1

CURRENT_STATES: Final = ("recovered", "failing", "unknown")
RECOVERY_STATES: Final = ("verified", "not_verified", "unknown")
LIFECYCLE_SIGNALS: Final = (
    "container_restart",
    "pod_replacement",
    "rollout_replacement",
    "insufficient_evidence",
    "conflicting_evidence",
)
RECOVERY_STATUSES: Final = (
    "restart_observed_recovered",
    "restart_observed_not_recovered",
    "insufficient_evidence",
    "conflicting_evidence",
)
EVIDENCE_GAPS: Final = (
    "missing_evidence",
    "stale_evidence",
    "incomplete_evidence",
    "conflicting_evidence",
    "unassessed_finding",
    "delivery_uncertain",
    "delivery_failed",
)
PUBLICATION_STATES: Final = (
    "published",
    "published_receipt_unrecorded",
    "duplicate_suppressed",
    "reconciled_duplicate",
    "publish_uncertain",
    "awaiting_reconciliation",
    "failed",
)

_MAX_TARGETS: Final = 200
_MAX_FAILURES: Final = 32
_MAX_REFS: Final = 16


class LifecycleProjectionError(ValueError):
    """A tracked lifecycle row cannot be served as an operator answer."""


def detection_lifecycle_projection(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> JsonObject:
    """Return the lifecycle section for the retained tracked-state rows.

    ``now`` is the read time. A projection older than its own freshness budget
    describes a window the control plane has not refreshed, so its current
    state and recovery are withdrawn here rather than served as current. The
    failure history stays: those failures were observed, and a late read does
    not unobserve them.
    """

    read_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    try:
        targets = [_target(_mapping(row.get("value")), read_at) for row in rows[:_MAX_TARGETS]]
    except LifecycleProjectionError as error:
        return _unavailable(str(error))
    if len(rows) > _MAX_TARGETS:
        return _unavailable("target_limit_exceeded")

    targets.sort(key=lambda target: str(target["resource_ref"]))
    current = {state: 0 for state in CURRENT_STATES}
    recovery = {state: 0 for state in RECOVERY_STATES}
    gap_targets = 0
    failure_total = 0
    for target in targets:
        current[str(target["current_state"])] += 1
        recovery[str(target["recovery_state"])] += 1
        failure_total += int(cast(int, target["failure_count"]))
        if cast(Sequence[Any], target["evidence_gaps"]):
            gap_targets += 1
    return cast(
        JsonObject,
        {
            "status": "available",
            "unavailable_reason": None,
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "target_count": len(targets),
            "failure_total": failure_total,
            "gap_target_count": gap_targets,
            "counts": current,
            "recovery_counts": recovery,
            "cause_claim_supported": False,
            "execution_authority": False,
            "targets": targets,
        },
    )


def _unavailable(reason: str) -> JsonObject:
    """Report a named unavailable section instead of a partial answer."""

    return cast(
        JsonObject,
        {
            "status": "unavailable",
            "unavailable_reason": reason,
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "target_count": 0,
            "failure_total": 0,
            "gap_target_count": 0,
            "counts": {state: 0 for state in CURRENT_STATES},
            "recovery_counts": {state: 0 for state in RECOVERY_STATES},
            "cause_claim_supported": False,
            "execution_authority": False,
            "targets": [],
        },
    )


def _target(value: Mapping[str, Any], read_at: datetime) -> JsonObject:
    if value.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
        raise LifecycleProjectionError("unsupported_schema")
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise LifecycleProjectionError("malformed_projection")
    if snapshot.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
        raise LifecycleProjectionError("unsupported_schema")
    if snapshot.get("cause_claim_supported") is not False:
        raise LifecycleProjectionError("cause_claim_rejected")
    if snapshot.get("execution_authority") is not False:
        raise LifecycleProjectionError("authority_claim_rejected")

    current_state = _member(snapshot.get("current_state"), CURRENT_STATES)
    current_signal = _optional_member(snapshot.get("current_signal"), LIFECYCLE_SIGNALS)
    current_observed_at = _optional_text(snapshot.get("current_state_observed_at"))
    recovery_state = _member(snapshot.get("recovery_state"), RECOVERY_STATES)
    recovery_verified_at = _optional_text(snapshot.get("recovery_verified_at"))
    if (recovery_state == "verified") != (recovery_verified_at is not None):
        raise LifecycleProjectionError("malformed_projection")
    if current_state == "recovered" and recovery_state != "verified":
        raise LifecycleProjectionError("unverified_recovery_rejected")

    failures = snapshot.get("failures")
    if not isinstance(failures, Sequence) or isinstance(failures, (str, bytes)):
        raise LifecycleProjectionError("malformed_projection")
    if len(failures) > _MAX_FAILURES:
        raise LifecycleProjectionError("failure_limit_exceeded")
    if snapshot.get("failure_count") != len(failures):
        raise LifecycleProjectionError("malformed_projection")

    generated_at = _text(snapshot.get("generated_at"))
    budget = _number(snapshot.get("freshness_budget_seconds"))
    gaps = _members(snapshot.get("evidence_gaps"), EVIDENCE_GAPS)
    age = _age_seconds(generated_at, read_at)
    stale = age > budget
    if stale:
        current_state = "unknown"
        current_signal = None
        current_observed_at = None
        recovery_state = "unknown"
        recovery_verified_at = None
        if "stale_evidence" not in gaps:
            gaps.append("stale_evidence")
    return cast(
        JsonObject,
        {
            "resource_ref": _text(snapshot.get("resource_ref")),
            "generated_at": generated_at,
            "freshness_budget_seconds": budget,
            "projection_age_seconds": age,
            "stale": stale,
            "current_state": current_state,
            "current_signal": current_signal,
            "current_state_observed_at": current_observed_at,
            "recovery_state": recovery_state,
            "recovery_verified_at": recovery_verified_at,
            "failure_count": len(failures),
            "failures": [_failure(item) for item in failures],
            "retained_record_count": _count(snapshot.get("retained_record_count")),
            "evidence_gaps": gaps,
            "evidence_gap_details": _texts(snapshot.get("evidence_gap_details")),
            "delivery_counts": _delivery_counts(snapshot.get("delivery_counts")),
        },
    )


def _age_seconds(generated_at: str, read_at: datetime) -> float:
    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as error:
        raise LifecycleProjectionError("malformed_projection") from error
    if generated.tzinfo is None:
        raise LifecycleProjectionError("malformed_projection")
    return max((read_at - generated.astimezone(UTC)).total_seconds(), 0.0)


def _failure(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise LifecycleProjectionError("malformed_projection")
    recovery_closed = value.get("recovery_closed")
    if recovery_closed is not None and not isinstance(recovery_closed, bool):
        raise LifecycleProjectionError("malformed_projection")
    evidence_complete = value.get("evidence_complete")
    if not isinstance(evidence_complete, bool):
        raise LifecycleProjectionError("malformed_projection")
    if recovery_closed is True and not evidence_complete:
        raise LifecycleProjectionError("unverified_recovery_rejected")
    refs = _texts(value.get("evidence_refs"))
    if len(refs) > _MAX_REFS:
        raise LifecycleProjectionError("evidence_ref_limit_exceeded")
    return cast(
        JsonObject,
        {
            "idempotency_key": _text(value.get("idempotency_key")),
            "signal": _member(value.get("signal"), LIFECYCLE_SIGNALS),
            "occurred_at": _text(value.get("occurred_at")),
            "recorded_at": _text(value.get("recorded_at")),
            "detection_latency_seconds": _number(value.get("detection_latency_seconds")),
            "evidence_complete": evidence_complete,
            "recovery_closed": recovery_closed,
            "recovery_status": _optional_member(value.get("recovery_status"), RECOVERY_STATUSES),
            "publication": _member(value.get("publication"), PUBLICATION_STATES),
            "assessed_by": _optional_text(value.get("assessed_by")),
            "evidence_refs": refs,
            "evidence_gaps": _texts(value.get("evidence_gaps")),
        },
    )


def _delivery_counts(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise LifecycleProjectionError("malformed_projection")
    counts: dict[str, JsonValue] = {}
    for state in PUBLICATION_STATES:
        counts[state] = _count(value.get(state, 0))
    if set(value) - set(PUBLICATION_STATES):
        raise LifecycleProjectionError("unknown_publication_state")
    return counts


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleProjectionError("malformed_projection")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleProjectionError("malformed_projection")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _texts(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LifecycleProjectionError("malformed_projection")
    return [_text(item) for item in value]


def _member(value: object, allowed: Sequence[str]) -> str:
    text = _text(value)
    if text not in allowed:
        raise LifecycleProjectionError("malformed_projection")
    return text


def _optional_member(value: object, allowed: Sequence[str]) -> str | None:
    return None if value is None else _member(value, allowed)


def _members(value: object, allowed: Sequence[str]) -> list[str]:
    members = [_member(item, allowed) for item in _texts(value)]
    if len(set(members)) != len(members):
        raise LifecycleProjectionError("malformed_projection")
    return members


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleProjectionError("malformed_projection")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise LifecycleProjectionError("malformed_projection")
    return float(value)


__all__ = [
    "CURRENT_STATES",
    "EVIDENCE_GAPS",
    "LIFECYCLE_SCHEMA_VERSION",
    "LIFECYCLE_SIGNALS",
    "PUBLICATION_STATES",
    "RECOVERY_STATES",
    "RECOVERY_STATUSES",
    "LifecycleProjectionError",
    "detection_lifecycle_projection",
]
