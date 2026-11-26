"""One current Forseti typed-proposal review per proposal in the durable ledger.

A typed-proposal review key names one proposal, so the ledger keeps exactly one row
per proposal. A newer generated review supersedes the older revision, its embedded
outbox, and appends Saga lineage in one compare-and-set; an older revision never
replaces a newer one. Different evidence at the same instant is tombstoned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fdai.core.assurance_twin.posture_activity import AssuranceTwinReviewActivity
from fdai.delivery.persistence.assurance_twin_outbox import (
    _advance_publication,
    _audit_lineage,
    _pending_publication,
)
from fdai.delivery.persistence.state_store_assurance_twin_conflict import (
    has_conflict_marker,
    with_conflict_marker,
)
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.delivery.persistence.state_store_assurance_twin_posture import (
        AssuranceTwinLedgerWrite,
    )

_MAX_ATTEMPTS = 8


class AssuranceTwinProposalReviewMixin:
    """Supersede older typed-proposal review revisions atomically."""

    _store: StateStore

    async def record_proposal_review(
        self,
        review: IacReview,
        *,
        freshness: str,
        activity_id: str,
        correlation_id: str,
        evidence_source_revision: str,
        source_confirmed: bool,
        activity: AssuranceTwinReviewActivity,
    ) -> AssuranceTwinLedgerWrite:
        """Persist the newest exact review for ``review.pr_ref``.

        Returns ``created=True`` when this call created or advanced the one current
        row. An identical replay is a read-only no-op, a delayed older revision is
        rejected with the newer stored digest, and different evidence generated at
        the same instant receives a durable conflict marker.
        """

        from fdai.delivery.persistence import state_store_assurance_twin_posture as ledger

        ledger._check_enum("freshness", freshness, ledger._ALLOWED_FRESHNESS)
        ledger._check_enum("review verdict", review.verdict, ledger._ALLOWED_REVIEW_VERDICTS)
        ledger._check_bounded_findings(review.findings)
        if activity.activity_id != activity_id or activity.freshness.value != freshness:
            raise ValueError("review publication must match the persisted activity and freshness")
        correlation = ledger._privacy_safe_identity(correlation_id)
        key = ledger.change_review_state_key(review.review_key)
        body = ledger._change_review_body(review, freshness=freshness, reason_codes=())
        digest = ledger.evidence_body_digest(body)
        value: dict[str, Any] = {
            **ledger._with_provenance(
                body,
                activity_id=activity_id,
                correlation_id=correlation,
                digest=digest,
                evidence_source_revision=evidence_source_revision,
                source_confirmed=source_confirmed,
            ),
            "revision": 1,
            **_pending_publication(activity, owner="Forseti", digest=digest, revision=1),
        }
        lineage = {"correlation_id": correlation, "digest": digest, "owner": "Forseti", "key": key}
        if await self._store.write_state_with_audit_if_absent(
            key, value, _audit_lineage(kind="review_recorded", revision=1, **lineage)
        ):
            return ledger.AssuranceTwinLedgerWrite(key=key, created=True, evidence_digest=digest)
        for _attempt in range(_MAX_ATTEMPTS):
            existing = await self._store.read_state(key)
            if existing is None:
                raise RuntimeError("assurance twin proposal review row disappeared")
            stored_digest = ledger._stored_digest(existing)
            stored_time = ledger._stored_canonical_timestamp(existing)
            incoming_time = str(value["generated_at"])
            if stored_time is not None and stored_time > incoming_time:
                return ledger.AssuranceTwinLedgerWrite(
                    key=key,
                    created=False,
                    evidence_digest=digest,
                    conflict=has_conflict_marker(existing),
                    stored_evidence_digest=stored_digest,
                )
            revision = ledger._stored_revision(existing)
            if stored_time == incoming_time:
                if has_conflict_marker(existing):
                    return ledger.AssuranceTwinLedgerWrite(
                        key=key,
                        created=False,
                        evidence_digest=digest,
                        conflict=True,
                        stored_evidence_digest=stored_digest,
                    )
                if (
                    ledger._stored_comparison_digest(existing) == digest
                    and existing.get("evidence_source_revision") == evidence_source_revision
                ):
                    return ledger.AssuranceTwinLedgerWrite(
                        key=key,
                        created=False,
                        evidence_digest=digest,
                        stored_evidence_digest=stored_digest,
                    )
                if await self._store.compare_and_set_state_with_audit(
                    key,
                    {
                        **with_conflict_marker(
                            existing,
                            reason_code=ledger.REVIEW_CONFLICT_REASON_CODE,
                            stored_evidence_digest=stored_digest,
                            rejected_evidence_digest=digest,
                        ),
                        "revision": revision + 1,
                        "publication_outbox": None,
                    },
                    expected_revision=revision,
                    audit_entry=_audit_lineage(
                        kind="review_conflict_marked", revision=revision + 1, **lineage
                    ),
                ):
                    return ledger.AssuranceTwinLedgerWrite(
                        key=key,
                        created=False,
                        evidence_digest=digest,
                        conflict=True,
                        stored_evidence_digest=stored_digest,
                    )
                continue
            if await self._store.compare_and_set_state_with_audit(
                key,
                {
                    **value,
                    "revision": revision + 1,
                    **_advance_publication(value, revision=revision + 1),
                },
                expected_revision=revision,
                audit_entry={
                    **_audit_lineage(kind="review_superseded", revision=revision + 1, **lineage),
                    "superseded_evidence_digest": stored_digest,
                },
            ):
                return ledger.AssuranceTwinLedgerWrite(
                    key=key,
                    created=True,
                    evidence_digest=digest,
                    stored_evidence_digest=stored_digest,
                )
        raise RuntimeError("assurance twin proposal review compare-and-set exceeded its bound")


__all__ = ["AssuranceTwinProposalReviewMixin"]
