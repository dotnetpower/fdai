"""Automatic demotion on unsafe chaos containment or recovery evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
)
from fdai.core.risk_gate import ActionPromotionRegistry


@dataclass(frozen=True, slots=True)
class ChaosPromotionObservation:
    observed_at: datetime
    audit_ref: str
    runner_version: str
    containment_compliant: bool
    recovery_within_objective: bool
    telemetry_complete: bool
    stop_observed: bool
    rollback_succeeded: bool
    policy_escapes: int = 0

    def regression_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.containment_compliant:
            reasons.append("impact_outside_envelope")
        if not self.recovery_within_objective:
            reasons.append("recovery_objective_missed")
        if not self.telemetry_complete:
            reasons.append("telemetry_incomplete")
        if not self.stop_observed:
            reasons.append("stop_condition_missed")
        if not self.rollback_succeeded:
            reasons.append("rollback_failed")
        if self.policy_escapes > 0:
            reasons.append("policy_escape")
        return tuple(reasons)


class ChaosPromotionGuard:
    def __init__(
        self,
        *,
        scenario_ledger: ScenarioPromotionLedger,
        action_registry: ActionPromotionRegistry,
    ) -> None:
        self._scenario_ledger = scenario_ledger
        self._action_registry = action_registry

    def observe(
        self,
        *,
        key: ScenarioEvidenceKey,
        action_type_names: tuple[str, ...],
        observation: ChaosPromotionObservation,
    ) -> tuple[str, ...]:
        reasons = observation.regression_reasons()
        if not reasons or not self._scenario_ledger.is_enforce_eligible(key):
            return reasons
        identity = hashlib.sha256(
            f"{key.scenario_id}|{observation.observed_at.isoformat()}|{'|'.join(reasons)}".encode()
        ).hexdigest()
        self._scenario_ledger.append(
            ScenarioPromotionEvidence(
                evidence_id=f"regression-{identity[:24]}",
                key=key,
                from_state=ScenarioPromotionState.ENFORCE_ELIGIBLE,
                to_state=ScenarioPromotionState.REGRESSED,
                actor_principal="Mimir",
                audit_ref=observation.audit_ref,
                observed_at=observation.observed_at,
                runner_version=observation.runner_version,
                stop_condition_observed=observation.stop_observed,
                rollback_succeeded=observation.rollback_succeeded,
                blast_radius_compliant=observation.containment_compliant,
                regression_reasons=reasons,
            )
        )
        for action_type_name in action_type_names:
            self._action_registry.demote(action_type_name)
        return reasons


__all__ = ["ChaosPromotionGuard", "ChaosPromotionObservation"]
