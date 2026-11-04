"""Durable, idempotent record of value claim settlements and their Outcome Assurance bridge.

A settlement is immutable evidence: recording the same settlement twice is a no-op and a
different settlement under one digest key cannot exist. The bridge only reshapes a settlement
for the read-only Outcome Assurance projection. It never upgrades an unsettled claim to a
measured one and it grants no authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fdai.core.measurement.outcome_assurance import (
    ConfidenceInterval,
    OutcomeEvidenceState,
    OutcomeMeasurement,
)
from fdai.core.measurement.value_claim import (
    ValueClaimDeclaration,
    ValueClaimSettlement,
    ValueClaimStatus,
)
from fdai.shared.providers.state_store import StateStore

_KEY_PREFIX = "value-claim:settlement:"
_ACTOR = "fdai.core.measurement.value_claim_ledger"
_MEASURED_STATUSES = frozenset({ValueClaimStatus.IMPROVED, ValueClaimStatus.NO_SIGNIFICANT_CHANGE})


@dataclass(frozen=True, slots=True)
class StateStoreValueClaimLedger:
    """Record each settlement once, keyed by its replay-stable digest."""

    store: StateStore

    async def record(
        self,
        declaration: ValueClaimDeclaration,
        settlement: ValueClaimSettlement,
    ) -> bool:
        """Persist one settlement and return whether this call created it."""

        if settlement.claim_id != declaration.claim_id or settlement.unit is not declaration.unit:
            raise ValueError("value claim settlement does not match its declaration")
        record = _record(declaration, settlement)
        key = _key(settlement.claim_id, settlement.settlement_digest)
        created = await self.store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "event_id": f"value-claim:{settlement.settlement_digest}",
                "actor": _ACTOR,
                "action_kind": "value_claim.settlement.recorded",
                **record,
            },
        )
        if not created and await self.store.read_state(key) != record:
            raise RuntimeError("value claim settlement conflicts with its durable record")
        return created

    async def read(self, claim_id: str, settlement_digest: str) -> Mapping[str, Any] | None:
        return await self.store.read_state(_key(claim_id, settlement_digest))


def outcome_measurement_from_settlement(
    declaration: ValueClaimDeclaration,
    settlement: ValueClaimSettlement,
) -> OutcomeMeasurement:
    """Reshape a settlement for the read-only projection without inventing evidence."""

    if settlement.claim_id != declaration.claim_id:
        raise ValueError("value claim settlement does not match its declaration")
    refs = settlement.evidence_refs
    if settlement.status in _MEASURED_STATUSES | {ValueClaimStatus.REGRESSED}:
        interval_low = settlement.treatment_interval_low
        interval_high = settlement.treatment_interval_high
        if interval_low is None or interval_high is None:
            raise ValueError("a settled value claim MUST carry its interval")
        return OutcomeMeasurement(
            objective_ref=declaration.objective_ref,
            metric=declaration.metric_name,
            state=(
                OutcomeEvidenceState.REGRESSED
                if settlement.status is ValueClaimStatus.REGRESSED
                else OutcomeEvidenceState.MEASURED
            ),
            current_value=_number(settlement.treatment_mean),
            baseline_value=_number(settlement.baseline_mean),
            target_value=_number(declaration.target_value),
            unit=declaration.unit.value,
            sample_size=settlement.treatment_sample_count,
            confidence_interval=ConfidenceInterval(
                low=float(interval_low), high=float(interval_high)
            ),
            source_time=settlement.source_time,
            evidence_refs=refs,
        )
    state = (
        OutcomeEvidenceState.INSUFFICIENT_SAMPLE
        if settlement.status is ValueClaimStatus.UNSETTLED_INSUFFICIENT_SAMPLE
        else OutcomeEvidenceState.NOT_CONNECTED
    )
    return OutcomeMeasurement(
        objective_ref=declaration.objective_ref,
        metric=declaration.metric_name,
        state=state,
        unit=declaration.unit.value,
        evidence_refs=refs,
    )


def _number(value: Decimal | None) -> float:
    if value is None:
        raise ValueError("a settled value claim MUST carry its means")
    return float(value)


def _key(claim_id: str, settlement_digest: str) -> str:
    return f"{_KEY_PREFIX}{claim_id}:{settlement_digest}"


def _record(declaration: ValueClaimDeclaration, settlement: ValueClaimSettlement) -> dict[str, Any]:
    return {
        "claim_id": settlement.claim_id,
        "workflow_ref": declaration.workflow_ref,
        "workflow_version": declaration.workflow_version,
        "objective_ref": declaration.objective_ref,
        "metric_name": declaration.metric_name,
        "status": settlement.status.value,
        "unit": settlement.unit.value,
        "currency": settlement.currency,
        "settlement_digest": settlement.settlement_digest,
        "conservative_total_improvement": (
            None
            if settlement.conservative_total_improvement is None
            else str(settlement.conservative_total_improvement)
        ),
        "reason_codes": list(settlement.reason_codes),
        "evidence_refs": list(settlement.evidence_refs),
    }


__all__ = ["StateStoreValueClaimLedger", "outcome_measurement_from_settlement"]
