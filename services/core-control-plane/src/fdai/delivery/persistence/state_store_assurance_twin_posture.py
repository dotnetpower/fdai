"""Durable Assurance Twin posture and review projection over ``StateStore``.

The ledger stores already-computed shadow evidence without judging, approving,
or executing. Posture rows advance only to newer timestamps. Review rows are
idempotent by key, and different bodies under one key receive a durable conflict
marker through revision-fenced compare-and-set. Write-time size and identity
bounds mirror the Operator projection so every accepted row remains readable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts import AgentOperationalActivity

from fdai.core.assurance_twin.posture_activity import AssuranceTwinReviewActivity
from fdai.core.assurance_twin.report import PostureAssessmentReport
from fdai.delivery.persistence.assurance_twin_outbox import (
    CHANGE_REVIEW_STATE_PREFIX,
    POSTURE_REPORT_STATE_PREFIX,
    AssuranceTwinOutboxMixin,
    _advance_publication,
    _audit_lineage,
    _pending_publication,
)
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.state_store import StateStore

REVIEW_CONFLICT_REASON_CODE = "assurance_twin_review_key_conflict"
"""Reason code carried by the durable conflict marker and the unavailable tip."""

POSTURE_CONFLICT_REASON_CODE = "assurance_twin_posture_timestamp_conflict"
"""Reason code for different posture evidence generated at the same instant."""

CONFLICT_MARKER_FIELD = "conflict"
"""Row field that makes a same-key different-digest conflict durable."""

_REVISION_FIELD = "revision"
_PUBLICATION_FIELD = "publication_outbox"
"""Optimistic-concurrency counter excluded from evidence identity."""

_MAX_CONFLICT_CAS_ATTEMPTS = 8
_MAX_RECENT_CHANGE_REVIEWS = 1000
"""Bound lost compare-and-set retries so a broken store cannot spin."""

_MAX_POSTURE_CAS_ATTEMPTS = 8
"""Bound on retrying a posture advance after a concurrent writer wins."""

_REVIEW_KEY_MAX_CHARS = 256
"""Match the Operator detail lookup bound without a cross-service import."""

_MAX_FINDINGS = 200
"""Match the Operator finding-list bound at the write boundary."""

_MAX_LIST_ITEMS = 200
_MAX_TEXT_CHARS = 512
"""Match the Operator list and text bounds at the write boundary."""

_MAX_EVIDENCE_SOURCE_REVISION_CHARS = 512
"""Match the Operator provenance identity bound."""

_ALLOWED_FRESHNESS = frozenset({"fresh", "stale", "unavailable", "unknown"})
_ALLOWED_REVIEW_VERDICTS = frozenset({"clear", "needs_review", "blocked"})
_ALLOWED_FINDING_SEVERITIES = frozenset({"low", "medium", "high", "critical"})

#: Exclude write provenance and conflict history from evidence identity.
_PROVENANCE_FIELDS = frozenset(
    {
        "activity_id",
        "correlation_id",
        "evidence_digest",
        "evidence_source_revision",
        CONFLICT_MARKER_FIELD,
        _REVISION_FIELD,
        _PUBLICATION_FIELD,
    }
)


def posture_report_state_key(scope: str) -> str:
    """Return the deterministic latest-report key for ``scope``."""

    if not scope.strip():
        raise ValueError("assurance twin posture scope MUST be non-empty")
    return f"{POSTURE_REPORT_STATE_PREFIX}{scope}"


def change_review_state_key(review_key: str) -> str:
    """Return the bounded deterministic key for one change review."""

    if not review_key.strip():
        raise ValueError("assurance twin review key MUST be non-empty")
    if len(review_key) > _REVIEW_KEY_MAX_CHARS:
        raise ValueError(f"assurance twin review key MUST be <= {_REVIEW_KEY_MAX_CHARS} characters")
    return f"{CHANGE_REVIEW_STATE_PREFIX}{review_key}"


def _check_bounded_findings(findings: Sequence[Any]) -> None:
    """Reject findings the Operator projection cannot render exactly."""

    if len(findings) > _MAX_FINDINGS:
        raise ValueError(
            f"assurance twin findings MUST number <= {_MAX_FINDINGS}, got {len(findings)}"
        )
    for finding in findings:
        _check_enum("finding severity", finding.severity, _ALLOWED_FINDING_SEVERITIES)
        _check_bounded_string_list(finding.evidence_refs, field="finding evidence_refs")


def _check_enum(name: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise ValueError(f"assurance twin {name} is not projectable: {value!r}")


def _check_bounded_string_list(items: Sequence[object], *, field: str) -> None:
    """Reject a string list the Operator projection cannot render exactly."""

    if len(items) > _MAX_LIST_ITEMS:
        raise ValueError(
            f"assurance twin {field} MUST number <= {_MAX_LIST_ITEMS}, got {len(items)}"
        )
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"assurance twin {field} entries MUST be non-blank strings")
        if len(item) > _MAX_TEXT_CHARS:
            raise ValueError(
                f"assurance twin {field} entries MUST be <= {_MAX_TEXT_CHARS} characters"
            )
        if item in seen:
            raise ValueError(
                f"assurance twin {field} entries MUST be unique, got a duplicate {item!r}"
            )
        seen.add(item)


def evidence_body_digest(body: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 digest of one evidence body."""

    material = {key: value for key, value in body.items() if key not in _PROVENANCE_FIELDS}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class AssuranceTwinLedgerWrite:
    """Result of one durable posture/review write."""

    key: str
    created: bool
    """``True`` when this call created or advanced the durable row.

    For a posture report it is ``False`` when the same or a newer report is
    already durable; for a change review it is ``False`` on redelivery of an
    existing ``review_key``.
    """

    evidence_digest: str
    """SHA-256 digest of the evidence body this call carried."""

    conflict: bool = False
    """``True`` when an existing row under the same identity holds a
    different evidence body, or already carries a durable conflict marker.
    The stored evidence body is preserved and the row is tombstoned; the
    caller MUST fail closed rather than announce either version as
    authoritative.
    """

    stored_evidence_digest: str | None = None
    """Digest of the body that remains durable when it differs from
    ``evidence_digest``."""


class StateStoreAssuranceTwinPostureLedger(AssuranceTwinOutboxMixin):
    """Durable posture-report and change-review projection over ``StateStore``."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def record_posture_report(
        self,
        report: PostureAssessmentReport,
        *,
        freshness: str,
        reason_codes: tuple[str, ...] = (),
        activity_id: str,
        correlation_id: str,
        evidence_source_revision: str,
        activity: AgentOperationalActivity | AssuranceTwinReviewActivity | None = None,
    ) -> AssuranceTwinLedgerWrite:
        """Persist ``report`` as the latest snapshot for its scope.

        Raises:
            ValueError: when ``report.findings`` exceeds
                :data:`_MAX_FINDINGS`, a finding's ``evidence_refs`` fails
                :func:`_check_bounded_string_list`, ``reason_codes`` fails
                :func:`_check_bounded_string_list`, or
                ``evidence_source_revision`` is blank or exceeds
                :data:`_MAX_EVIDENCE_SOURCE_REVISION_CHARS` - all rejected
                before any write so a report this call persists is always
                fully renderable by the Operator API's projection.
        """

        _check_enum("freshness", freshness, _ALLOWED_FRESHNESS)
        _check_bounded_findings(report.findings)
        _check_bounded_string_list(reason_codes, field="reason_codes")
        correlation_identity = _privacy_safe_identity(correlation_id)
        key = posture_report_state_key(report.scope)
        body: dict[str, Any] = {
            **report.to_dict(),
            "generated_at": _canonical_timestamp(report.generated_at),
            "freshness": freshness,
            "reason_codes": list(reason_codes),
        }
        digest = evidence_body_digest(body)
        publication = _pending_publication(activity, owner="Heimdall", digest=digest, revision=1)
        if activity is not None and (
            activity.activity_id != activity_id or activity.freshness.value != freshness
        ):
            raise ValueError("posture publication must match the persisted activity and freshness")
        value = {
            **_with_provenance(
                body,
                activity_id=activity_id,
                correlation_id=correlation_identity,
                digest=digest,
                evidence_source_revision=evidence_source_revision,
            ),
            _REVISION_FIELD: 1,
            **publication,
        }
        if await self._store.write_state_with_audit_if_absent(
            key,
            value,
            _audit_lineage(
                kind="posture_recorded",
                correlation_id=correlation_identity,
                digest=digest,
                revision=1,
                owner="Heimdall",
                key=key,
            ),
        ):
            return AssuranceTwinLedgerWrite(key=key, created=True, evidence_digest=digest)
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError(
                "assurance twin posture row disappeared after losing its create race"
            )
        return await self._advance_posture_report(
            key=key,
            value=value,
            digest=digest,
            correlation_id=correlation_identity,
            attempts_remaining=_MAX_POSTURE_CAS_ATTEMPTS,
            existing=existing,
        )

    async def _advance_posture_report(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        digest: str,
        correlation_id: str,
        attempts_remaining: int,
        existing: Mapping[str, Any],
    ) -> AssuranceTwinLedgerWrite:
        """Atomically advance one scope only to a newer generated timestamp."""

        incoming_generated_at = str(value["generated_at"])
        existing_generated_at = _stored_canonical_timestamp(existing)
        stored_digest = _stored_digest(existing)
        if existing_generated_at is not None and existing_generated_at > incoming_generated_at:
            return AssuranceTwinLedgerWrite(
                key=key,
                created=False,
                evidence_digest=digest,
                conflict=_has_conflict_marker(existing),
                stored_evidence_digest=stored_digest,
            )
        if existing_generated_at == incoming_generated_at:
            if _has_conflict_marker(existing):
                return AssuranceTwinLedgerWrite(
                    key=key,
                    created=False,
                    evidence_digest=digest,
                    conflict=True,
                    stored_evidence_digest=stored_digest,
                )
            if _stored_comparison_digest(existing) == digest:
                return AssuranceTwinLedgerWrite(
                    key=key,
                    created=False,
                    evidence_digest=digest,
                    stored_evidence_digest=stored_digest,
                )
            return await self._mark_posture_conflict(
                key=key,
                value=value,
                digest=digest,
                correlation_id=correlation_id,
                attempts_remaining=attempts_remaining,
                existing=existing,
            )
        if attempts_remaining <= 0:
            raise RuntimeError("assurance twin posture compare-and-set exceeded its retry bound")
        current_revision = _stored_revision(existing)
        advanced = await self._store.compare_and_set_state_with_audit(
            key,
            {
                **value,
                _REVISION_FIELD: current_revision + 1,
                **_advance_publication(value, revision=current_revision + 1),
            },
            expected_revision=current_revision,
            audit_entry=_audit_lineage(
                kind="posture_advanced",
                correlation_id=correlation_id,
                digest=digest,
                revision=current_revision + 1,
                owner="Heimdall",
                key=key,
            ),
        )
        if advanced:
            return AssuranceTwinLedgerWrite(key=key, created=True, evidence_digest=digest)
        replay = await self._store.read_state(key)
        if replay is None:
            raise RuntimeError(
                "assurance twin posture row disappeared during a compare-and-set race"
            )
        return await self._advance_posture_report(
            key=key,
            value=value,
            digest=digest,
            correlation_id=correlation_id,
            attempts_remaining=attempts_remaining - 1,
            existing=replay,
        )

    async def _mark_posture_conflict(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        digest: str,
        correlation_id: str,
        attempts_remaining: int,
        existing: Mapping[str, Any],
    ) -> AssuranceTwinLedgerWrite:
        """Tombstone different evidence generated for one scope at one instant."""

        if attempts_remaining <= 0:
            raise RuntimeError(
                "assurance twin posture conflict compare-and-set exceeded its retry bound"
            )
        stored_digest = _stored_digest(existing)
        current_revision = _stored_revision(existing)
        advanced = await self._store.compare_and_set_state_with_audit(
            key,
            {
                **_with_conflict_marker(
                    existing,
                    reason_code=POSTURE_CONFLICT_REASON_CODE,
                    stored_evidence_digest=stored_digest,
                    rejected_evidence_digest=digest,
                ),
                _REVISION_FIELD: current_revision + 1,
                _PUBLICATION_FIELD: None,
            },
            expected_revision=current_revision,
            audit_entry={
                "action_kind": "assurance_twin.posture_conflict_marked",
                "actor": "fdai.system",
                "mode": "shadow",
                "correlation_id": correlation_id,
                "idempotency_key": (
                    f"assurance-twin-posture-conflict:{_privacy_safe_identity(key)}:{digest}"
                ),
            },
        )
        if advanced:
            return AssuranceTwinLedgerWrite(
                key=key,
                created=False,
                evidence_digest=digest,
                conflict=True,
                stored_evidence_digest=stored_digest,
            )
        replay = await self._store.read_state(key)
        if replay is None:
            raise RuntimeError("assurance twin posture row disappeared during a conflict race")
        return await self._advance_posture_report(
            key=key,
            value=value,
            digest=digest,
            correlation_id=correlation_id,
            attempts_remaining=attempts_remaining - 1,
            existing=replay,
        )

    async def record_change_review(
        self,
        review: IacReview,
        *,
        freshness: str,
        reason_codes: tuple[str, ...] = (),
        activity_id: str,
        correlation_id: str,
        evidence_source_revision: str,
        activity: AgentOperationalActivity | AssuranceTwinReviewActivity | None = None,
    ) -> AssuranceTwinLedgerWrite:
        """Persist one bounded review and durably tombstone key conflicts.

        Matching redelivery is a read-only no-op. Conflicting redelivery uses
        a revision-fenced compare-and-set so concurrent conflicts cannot
        replace or discard the durable tombstone.
        """

        _check_enum("freshness", freshness, _ALLOWED_FRESHNESS)
        _check_enum("review verdict", review.verdict, _ALLOWED_REVIEW_VERDICTS)
        _check_bounded_findings(review.findings)
        _check_bounded_string_list(reason_codes, field="reason_codes")
        correlation_identity = _privacy_safe_identity(correlation_id)
        key = change_review_state_key(review.review_key)
        body = _change_review_body(review, freshness=freshness, reason_codes=reason_codes)
        digest = evidence_body_digest(body)
        publication = _pending_publication(activity, owner="Forseti", digest=digest, revision=1)
        if activity is not None and (
            activity.activity_id != activity_id or activity.freshness.value != freshness
        ):
            raise ValueError("review publication must match the persisted activity and freshness")
        created = await self._store.write_state_with_audit_if_absent(
            key,
            {
                **_with_provenance(
                    body,
                    activity_id=activity_id,
                    correlation_id=correlation_identity,
                    digest=digest,
                    evidence_source_revision=evidence_source_revision,
                ),
                _REVISION_FIELD: 1,
                **publication,
            },
            _audit_lineage(
                kind="review_recorded",
                correlation_id=correlation_identity,
                digest=digest,
                revision=1,
                owner="Forseti",
                key=key,
            ),
        )
        if created:
            return AssuranceTwinLedgerWrite(key=key, created=True, evidence_digest=digest)
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("assurance twin review row disappeared after losing its create race")
        return await self._resolve_conflict(
            key=key,
            digest=digest,
            existing=existing,
            correlation_id=correlation_identity,
            attempts_remaining=_MAX_CONFLICT_CAS_ATTEMPTS,
        )

    async def _resolve_conflict(
        self,
        *,
        key: str,
        digest: str,
        existing: Mapping[str, Any],
        correlation_id: str,
        attempts_remaining: int,
    ) -> AssuranceTwinLedgerWrite:
        """Reconcile a same-key redelivery against ``existing`` atomically.

        Only one path ever mutates a row after creation: the atomic
        tombstone write below. So a lost compare-and-set means a concurrent
        caller just tombstoned the row (or is about to be observed as
        having done so); re-reading and recursing here always terminates in
        the branch that returns ``conflict=True`` without writing again.
        """

        stored_digest = _stored_digest(existing)
        stored_comparison_digest = _stored_comparison_digest(existing)
        if _has_conflict_marker(existing):
            return AssuranceTwinLedgerWrite(
                key=key,
                created=False,
                evidence_digest=digest,
                conflict=True,
                stored_evidence_digest=stored_digest,
            )
        if stored_comparison_digest == digest:
            return await self._confirm_matching_replay(
                key=key,
                digest=digest,
                existing=existing,
                correlation_id=correlation_id,
                attempts_remaining=attempts_remaining,
            )
        if attempts_remaining <= 0:
            raise RuntimeError(
                "assurance twin review conflict compare-and-set exceeded its retry bound"
            )
        current_revision = _stored_revision(existing)
        tombstoned = {
            **_with_conflict_marker(
                existing,
                reason_code=REVIEW_CONFLICT_REASON_CODE,
                stored_evidence_digest=stored_digest,
                rejected_evidence_digest=digest,
            ),
            _REVISION_FIELD: current_revision + 1,
            _PUBLICATION_FIELD: None,
        }
        advanced = await self._store.compare_and_set_state_with_audit(
            key,
            tombstoned,
            expected_revision=current_revision,
            audit_entry={
                "action_kind": "assurance_twin.review_conflict_marked",
                "actor": "fdai.system",
                "mode": "shadow",
                "correlation_id": correlation_id,
                "idempotency_key": f"assurance-twin-review-conflict:{key}:{digest}",
            },
        )
        if advanced:
            return AssuranceTwinLedgerWrite(
                key=key,
                created=False,
                evidence_digest=digest,
                conflict=True,
                stored_evidence_digest=stored_digest,
            )
        replay = await self._store.read_state(key)
        if replay is None:
            raise RuntimeError(
                "assurance twin review row disappeared during a conflict compare-and-set race"
            )
        return await self._resolve_conflict(
            key=key,
            digest=digest,
            existing=replay,
            correlation_id=correlation_id,
            attempts_remaining=attempts_remaining - 1,
        )

    async def _confirm_matching_replay(
        self,
        *,
        key: str,
        digest: str,
        existing: Mapping[str, Any],
        correlation_id: str,
        attempts_remaining: int,
    ) -> AssuranceTwinLedgerWrite:
        """Confirm a matching replay without mutating state or audit history."""

        if attempts_remaining <= 0:
            raise RuntimeError("assurance twin review replay exceeded its retry bound")
        confirmed = await self._store.read_state(key)
        if confirmed is None:
            raise RuntimeError("assurance twin review row disappeared during replay confirmation")
        stored_digest = _stored_digest(confirmed)
        if _has_conflict_marker(confirmed):
            return AssuranceTwinLedgerWrite(
                key=key,
                created=False,
                evidence_digest=digest,
                conflict=True,
                stored_evidence_digest=stored_digest,
            )
        if (
            _stored_revision(confirmed) != _stored_revision(existing)
            or _stored_comparison_digest(confirmed) != digest
        ):
            return await self._resolve_conflict(
                key=key,
                digest=digest,
                existing=confirmed,
                correlation_id=correlation_id,
                attempts_remaining=attempts_remaining - 1,
            )
        return AssuranceTwinLedgerWrite(key=key, created=False, evidence_digest=digest)

    async def read_latest_posture_report(self, scope: str) -> Mapping[str, Any] | None:
        """Return the latest durable posture report for ``scope``, if any."""

        return await self._store.read_state(posture_report_state_key(scope))

    async def read_recent_change_reviews(
        self,
        *,
        limit: int = 100,
    ) -> tuple[Mapping[str, Any], ...]:
        """Return up to ``limit`` durable change reviews, newest first."""

        if not 1 <= limit <= _MAX_RECENT_CHANGE_REVIEWS:
            raise ValueError(
                f"assurance twin review read limit MUST be in [1, {_MAX_RECENT_CHANGE_REVIEWS}]"
            )
        rows, total = await self._store.read_state_page(
            CHANGE_REVIEW_STATE_PREFIX,
            limit=_MAX_RECENT_CHANGE_REVIEWS,
        )
        if total > _MAX_RECENT_CHANGE_REVIEWS:
            raise RuntimeError("assurance twin review projection exceeds its bounded read capacity")
        ordered = sorted(rows, key=lambda item: str(item.get("review_key", "")))
        ordered.sort(
            key=lambda item: _stored_canonical_timestamp(item) or "",
            reverse=True,
        )
        return tuple(ordered[:limit])


def _with_provenance(
    body: Mapping[str, Any],
    *,
    activity_id: str,
    correlation_id: str,
    digest: str,
    evidence_source_revision: str,
) -> dict[str, Any]:
    _check_provenance_identity("activity_id", activity_id)
    _check_provenance_identity("correlation_id", correlation_id)
    _check_provenance_identity("evidence_source_revision", evidence_source_revision)
    return {
        **body,
        "activity_id": activity_id,
        "correlation_id": correlation_id,
        "evidence_digest": digest,
        "evidence_source_revision": evidence_source_revision,
    }


def _check_provenance_identity(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"assurance twin {name} MUST be non-blank")
    if len(value) > _MAX_EVIDENCE_SOURCE_REVISION_CHARS:
        raise ValueError(
            f"assurance twin {name} MUST be <= {_MAX_EVIDENCE_SOURCE_REVISION_CHARS} characters"
        )


def _change_review_body(
    review: IacReview,
    *,
    freshness: str,
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "pr_ref": review.pr_ref,
        "review_key": review.review_key,
        "verdict": review.verdict,
        "mode": review.mode.value,
        "generated_at": _canonical_timestamp(review.generated_at),
        "freshness": freshness,
        "reason_codes": list(reason_codes),
        "metadata": dict(review.metadata),
        "findings": [
            {
                "rule_id": finding.rule_id,
                "resource_type": finding.resource.resource_type,
                "resource_ref": finding.resource.ref,
                "severity": finding.severity,
                "reason": finding.reason,
                "evidence_refs": list(finding.evidence_refs),
            }
            for finding in review.findings
        ],
    }


def _canonical_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("assurance twin generated_at MUST be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("assurance twin generated_at MUST include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _privacy_safe_identity(value: str) -> str:
    if not value.strip():
        raise ValueError("assurance twin correlation_id MUST be non-blank")
    if len(value) > _MAX_EVIDENCE_SOURCE_REVISION_CHARS:
        raise ValueError(
            "assurance twin correlation_id MUST be "
            f"<= {_MAX_EVIDENCE_SOURCE_REVISION_CHARS} characters"
        )
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _stored_digest(existing: Mapping[str, Any] | None) -> str | None:
    """Return the durable row's evidence digest, recomputing it when absent.

    A row written before provenance existed carries no ``evidence_digest``;
    recomputing it from the stored body keeps replay comparison honest
    instead of treating a missing field as a match.
    """

    if existing is None:
        return None
    recorded = existing.get("evidence_digest")
    if isinstance(recorded, str) and recorded:
        return recorded
    return evidence_body_digest(existing)


def _stored_comparison_digest(existing: Mapping[str, Any]) -> str:
    body = {key: value for key, value in existing.items() if key not in _PROVENANCE_FIELDS}
    generated_at = body.get("generated_at")
    if isinstance(generated_at, str):
        try:
            body["generated_at"] = _canonical_timestamp(generated_at)
        except ValueError:
            pass
    return evidence_body_digest(body)


def _stored_revision(existing: Mapping[str, Any]) -> int:
    """Return the CAS revision, matching the backend's legacy ``0`` fallback."""

    revision = existing.get(_REVISION_FIELD)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return 0
    return revision


def _stored_canonical_timestamp(existing: Mapping[str, Any]) -> str | None:
    generated_at = existing.get("generated_at")
    if not isinstance(generated_at, str):
        return None
    try:
        return _canonical_timestamp(generated_at)
    except ValueError:
        return None


def _has_conflict_marker(existing: Mapping[str, Any] | None) -> bool:
    return existing is not None and isinstance(existing.get(CONFLICT_MARKER_FIELD), Mapping)


def _with_conflict_marker(
    existing: Mapping[str, Any],
    *,
    reason_code: str,
    stored_evidence_digest: str | None,
    rejected_evidence_digest: str,
) -> dict[str, Any]:
    """Return the stored row tombstoned with a content-free conflict marker.

    The preserved evidence body and its provenance are untouched; only the
    excluded-from-digest marker is added, so a reader can still verify the
    stored body while being forced to render the row unavailable.
    """

    return {
        **existing,
        CONFLICT_MARKER_FIELD: {
            "reason_code": reason_code,
            "stored_evidence_digest": stored_evidence_digest,
            "rejected_evidence_digest": rejected_evidence_digest,
        },
    }


__all__ = [
    "CHANGE_REVIEW_STATE_PREFIX",
    "CONFLICT_MARKER_FIELD",
    "POSTURE_CONFLICT_REASON_CODE",
    "POSTURE_REPORT_STATE_PREFIX",
    "REVIEW_CONFLICT_REASON_CODE",
    "AssuranceTwinLedgerWrite",
    "StateStoreAssuranceTwinPostureLedger",
    "change_review_state_key",
    "evidence_body_digest",
    "posture_report_state_key",
]
