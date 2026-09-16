"""Fail-closed bridge from independent effect receipts to A3-E reversion evidence.

The executor observation contract and the standing-authority reversion contract use
separate vocabularies because neither owns the other. This module is the only translation
boundary. It can preserve a verified effect or lower authority; it cannot convert unknown
evidence into pending/matched state, grant recovery authority, or mutate a registry.
"""

from __future__ import annotations

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
)
from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
)

_OUTCOME_DISPOSITIONS = {
    IndependentEffectOutcome.VERIFIED: EffectEvidenceDisposition.MATCHED,
    IndependentEffectOutcome.FAILED: EffectEvidenceDisposition.FAILED,
    IndependentEffectOutcome.MISSING: EffectEvidenceDisposition.MISSING,
    IndependentEffectOutcome.STALE: EffectEvidenceDisposition.STALE,
    IndependentEffectOutcome.CONFLICTING: EffectEvidenceDisposition.CONFLICTING,
    IndependentEffectOutcome.CENSORED: EffectEvidenceDisposition.CENSORED,
    IndependentEffectOutcome.UNAVAILABLE: EffectEvidenceDisposition.UNSCORABLE,
}


def effect_evidence_disposition(
    receipt: IndependentEffectObservationReceipt,
) -> EffectEvidenceDisposition:
    """Return the no-authority A3-E disposition for one exact observation receipt."""

    return _OUTCOME_DISPOSITIONS[receipt.outcome]


def requires_shadow_reversion(receipt: IndependentEffectObservationReceipt) -> bool:
    """Return whether the receipt can only preserve safety by returning to shadow."""

    return effect_evidence_disposition(receipt) is not EffectEvidenceDisposition.MATCHED


__all__ = ["effect_evidence_disposition", "requires_shadow_reversion"]
