"""Tests for the independent-observation to A3-E evidence bridge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.executor.effect_observation import (
    IndependentEffectObservationBinding,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
    ObservationQuality,
)
from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
)
from fdai.core.standing_authority.effect_evidence_bridge import (
    effect_evidence_disposition,
    requires_shadow_reversion,
)
from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
)

_NOW = datetime(2026, 9, 16, 5, 0, tzinfo=UTC)


def _receipt(outcome: IndependentEffectOutcome) -> IndependentEffectObservationReceipt:
    binding = IndependentEffectObservationBinding.create(
        action_id="action:vm-start",
        action_payload_digest="sha256:" + "1" * 64,
        target_digest="sha256:" + "2" * 64,
        source_revision="3" * 40,
        execution_path="direct_api",
        execution_origin=SafeguardExecutionOrigin.CORE,
        execution_venue=SafeguardExecutionVenue.CORE,
        safeguard_bundle_digest="sha256:" + "4" * 64,
        evidence_identity_digest="sha256:" + "5" * 64,
        evidence_record_digest="sha256:" + "6" * 64,
        evidence_record_revision=1,
        executor_receipt_digest="sha256:" + "7" * 64,
    )
    return IndependentEffectObservationReceipt.create(
        observation_id="observation:vm-start",
        binding=binding,
        quality=ObservationQuality(
            schema_version="1.0.0",
            evidence_window_start=_NOW - timedelta(seconds=1),
            evidence_window_end=_NOW + timedelta(seconds=1),
            source_recorded_at=_NOW,
            max_source_age_seconds=900,
            finality=ObservationFinality.FINAL,
            completeness=ObservationCompleteness.COMPLETE,
            containment=ObservationContainment.WITHIN_DECLARED_TARGET,
            conflicting_source_count=0,
            synthetic=False,
        ),
        outcome=outcome,
        reason="independent observation",
        observer_instance_id="observer:heimdall",
        executor_instance_id="executor:thor",
        source_instance_id="source:azure-arm",
        observed_at=_NOW,
        completed_at=_NOW,
        sequence=1,
        prior_receipt_digest=None,
    )


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (IndependentEffectOutcome.VERIFIED, EffectEvidenceDisposition.MATCHED),
        (IndependentEffectOutcome.FAILED, EffectEvidenceDisposition.FAILED),
        (IndependentEffectOutcome.MISSING, EffectEvidenceDisposition.MISSING),
        (IndependentEffectOutcome.STALE, EffectEvidenceDisposition.STALE),
        (IndependentEffectOutcome.CONFLICTING, EffectEvidenceDisposition.CONFLICTING),
        (IndependentEffectOutcome.CENSORED, EffectEvidenceDisposition.CENSORED),
        (IndependentEffectOutcome.UNAVAILABLE, EffectEvidenceDisposition.UNSCORABLE),
    ],
)
def test_every_observation_outcome_maps_to_a_fail_closed_a3e_disposition(
    outcome: IndependentEffectOutcome,
    expected: EffectEvidenceDisposition,
) -> None:
    receipt = _receipt(outcome)

    assert effect_evidence_disposition(receipt) is expected
    assert requires_shadow_reversion(receipt) is (outcome is not IndependentEffectOutcome.VERIFIED)
