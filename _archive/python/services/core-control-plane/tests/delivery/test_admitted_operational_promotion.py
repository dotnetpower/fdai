"""Operational-promotion evidence admission source tests."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.measurement.operational_promotion import (
    OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
    operational_promotion_evidence_digest,
    operational_promotion_scope_digest,
)
from fdai.delivery.measurement.admitted_operational_promotion import (
    AdmittedOperationalPromotionEvidenceSource,
)

from tests.core.measurement.test_operational_promotion import _passing_batch


class _Source:
    def __init__(self, batch):
        self._batch = replace(batch, decision_evidence=None)

    async def load_batch(self, **kwargs):
        assert kwargs["action_type_name"] == self._batch.action_type_name
        assert kwargs["fdai_revision"] == self._batch.fdai_revision
        assert kwargs["scenario_set_version"] == self._batch.scenario_set_version
        return self._batch


class _Provider:
    def __init__(self, admission):
        self._admission = admission
        self.request = None

    async def admit(self, **kwargs):
        self.request = kwargs
        return self._admission


async def test_source_attaches_only_exact_batch_admission() -> None:
    batch = _passing_batch()
    provider = _Provider(batch.decision_evidence)
    source = AdmittedOperationalPromotionEvidenceSource(
        source=_Source(batch),
        admission_provider=provider,
    )

    admitted = await source.load_batch(
        action_type_name=batch.action_type_name,
        fdai_revision=batch.fdai_revision,
        scenario_set_version=batch.scenario_set_version,
    )

    assert admitted.decision_evidence == batch.decision_evidence
    assert provider.request == {
        "evidence_digest": operational_promotion_evidence_digest(batch),
        "scope_digest": operational_promotion_scope_digest(batch),
        "purpose_id": OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
        "source_revision": batch.fdai_revision,
    }
