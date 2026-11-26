"""Bind durable decision-evidence admissions to promotion measurement batches."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.measurement.operational_promotion import (
    OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
    OperationalPromotionBatch,
    operational_promotion_evidence_digest,
    operational_promotion_scope_digest,
)
from fdai.core.measurement.operational_promotion_runner import (
    OperationalPromotionEvidenceSource,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider


class AdmittedOperationalPromotionEvidenceSource:
    """Attach one exact current admission before deterministic evaluation."""

    def __init__(
        self,
        *,
        source: OperationalPromotionEvidenceSource,
        admission_provider: DecisionEvidenceAdmissionProvider,
    ) -> None:
        self._source = source
        self._admission_provider = admission_provider

    async def load_batch(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> OperationalPromotionBatch:
        """Load one immutable batch and resolve its independently retained admission."""

        batch = await self._source.load_batch(
            action_type_name=action_type_name,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
        )
        admission = await self._admission_provider.admit(
            evidence_digest=operational_promotion_evidence_digest(batch),
            scope_digest=operational_promotion_scope_digest(batch),
            purpose_id=OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
            source_revision=batch.fdai_revision,
        )
        return replace(batch, decision_evidence=admission)


__all__ = ["AdmittedOperationalPromotionEvidenceSource"]
