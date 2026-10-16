"""Bounded asynchronous preparation for exact production replay verification."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.measurement.operational_promotion import (
    OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
    OperationalPromotionEvaluator,
    action_type_digest,
    operational_promotion_evidence_digest,
    operational_promotion_receipt_digest,
    operational_promotion_scope_digest,
)
from fdai.core.measurement.operational_promotion_runner import OperationalPromotionEvidenceSource
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.case_history import CaseHistoryMetadataStore
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

from .case_review import ImmutableCaseRef

if TYPE_CHECKING:
    from .promotion_review import ReviewedReplayPromotionEvidence

REVIEWED_REPLAY_PROMOTION_PURPOSE = "reviewed-replay-promotion"
_PREPARATION_SECONDS = 5


@dataclass(frozen=True, slots=True)
class PreparedReplayReview:
    """A single-use local proof, bounded by both admission expiry and elapsed time."""

    valid_from: datetime
    valid_until: datetime
    monotonic_deadline: float
    receipt_digest: str
    verification_bundle_digest: str
    evaluated_receipt_digest: str

    def current(self, now: datetime) -> bool:
        return (
            now.utcoffset() is not None
            and self.valid_from <= now < self.valid_until
            and monotonic() < self.monotonic_deadline
        )


async def prepare_replay_review(
    evidence: ReviewedReplayPromotionEvidence,
    *,
    source: OperationalPromotionEvidenceSource,
    admission_provider: DecisionEvidenceAdmissionProvider,
    materializer: CaseHistoryMaterializer,
    case_metadata: CaseHistoryMetadataStore,
    action_type: OntologyActionType,
    evaluator: OperationalPromotionEvaluator,
    clock: Callable[[], datetime],
) -> PreparedReplayReview | None:
    """Re-read sources and independently admit measurement and review, without retry.

    The deployment-owned admission provider must authenticate the retained independent
    review for REVIEWED_REPLAY_PROMOTION_PURPOSE. An inline reviewer or approval flag
    is never a substitute. Source checks describe this preparation instant only.
    """
    binding = evidence.reviewed_replay_binding
    if binding is None or not evidence.approved:
        return None
    if (
        action_type.name != evidence.action_type
        or action_type.version != evidence.action_type_version
        or action_type_digest(action_type) != evidence.action_type_digest
        or evaluator.policy_digest != evidence.promotion_policy_digest
    ):
        return None
    started = monotonic()
    async with asyncio.timeout(_PREPARATION_SECONDS):
        batch = await source.load_batch(
            action_type_name=evidence.action_type,
            fdai_revision=evidence.fdai_revision,
            scenario_set_version=evidence.scenario_set_version,
        )
        if (
            batch.action_type_name != evidence.action_type
            or batch.action_type_version != evidence.action_type_version
            or batch.action_type_digest != evidence.action_type_digest
            or batch.fdai_revision != evidence.fdai_revision
            or batch.scenario_set_version != evidence.scenario_set_version
            or batch.reviewed_replay_binding != binding
            or batch.sealed_at > clock()
        ):
            return None
        scope_digest = operational_promotion_scope_digest(batch)
        measurement_digest = operational_promotion_evidence_digest(batch)
        measurement_admission = await admission_provider.admit(
            evidence_digest=measurement_digest,
            scope_digest=scope_digest,
            purpose_id=OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
            source_revision=batch.fdai_revision,
        )
        review_admission = await admission_provider.admit(
            evidence_digest=evidence.reviewed_replay_digest,
            scope_digest=scope_digest,
            purpose_id=REVIEWED_REPLAY_PROMOTION_PURPOSE,
            source_revision=batch.fdai_revision,
        )
        if measurement_admission is None or review_admission is None:
            return None
        if (
            measurement_admission.receipt_digest == review_admission.receipt_digest
            or measurement_admission.verification_bundle_digest
            == review_admission.verification_bundle_digest
        ):
            return None
        evaluated = evaluator.evaluate(
            action_type, replace(batch, decision_evidence=measurement_admission)
        )
        if (
            not evaluated.ready
            or evaluated.evidence_digest != evidence.promotion_evidence_digest
            or evaluated.policy_digest != evidence.promotion_policy_digest
        ):
            return None
        source_deadlines: list[datetime] = []
        for reference in binding.immutable_case_refs:
            if (
                await materializer.current_revision_available(
                    case_ref=reference,
                    access_scope_digest=binding.access_scope_digest,
                    purpose=binding.purpose,
                    now=clock(),
                )
                is not True
            ):
                return None
            ref = ImmutableCaseRef.parse(reference)
            record = await case_metadata.latest(
                ref.case_id, access_scope_digest=binding.access_scope_digest
            )
            completed_at = clock()
            if record is None or (
                record.case_id != ref.case_id
                or record.revision != ref.revision
                or record.manifest_digest != ref.manifest_digest
                or record.access_scope_digest != binding.access_scope_digest
                or record.purpose != binding.purpose
                or record.deleted_at is not None
                or record.deletion_started_at is not None
                or record.storage_ref is None
                or not record.sealed_at <= completed_at < record.deletion_due_at
            ):
                return None
            # retention_until is a minimum retention promise; deletion_due_at
            # is the materializer's hard availability deadline, even on hold.
            source_deadlines.append(record.deletion_due_at)
        now = clock()
        if now >= min(source_deadlines):
            return None
        for admission, digest, purpose in (
            (
                measurement_admission,
                measurement_digest,
                OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
            ),
            (review_admission, evidence.reviewed_replay_digest, REVIEWED_REPLAY_PROMOTION_PURPOSE),
        ):
            if assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id=purpose,
                expected_source_revision=batch.fdai_revision,
                evaluated_at=now,
            ):
                return None
        return PreparedReplayReview(
            valid_from=now,
            valid_until=min(
                now + timedelta(seconds=_PREPARATION_SECONDS),
                measurement_admission.valid_until,
                review_admission.valid_until,
                *source_deadlines,
            ),
            monotonic_deadline=started + _PREPARATION_SECONDS,
            receipt_digest=measurement_admission.receipt_digest,
            verification_bundle_digest=measurement_admission.verification_bundle_digest,
            evaluated_receipt_digest=operational_promotion_receipt_digest(evaluated),
        )
