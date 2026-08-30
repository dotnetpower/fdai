"""Materialize complete operational decision lineage from durable exact artifacts."""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.ontology_platform.kinetics import ReconciliationStatus
from fdai.core.ontology_platform.reconciliation_contracts import ReconciliationOutcome
from fdai.core.operational_planning.hypothesis_lineage import (
    OperationalHypothesisLineage,
    OperationalHypothesisLineageProjector,
)
from fdai.core.operational_planning.kinetic_proposal import KineticActionProposal
from fdai.core.operational_planning.models import OperationalPlan
from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.delivery.prospective_lineage import build_prospective_lineage_records
from fdai.delivery.reconciliation_artifacts import (
    KineticSafetyReceipt,
    StateStoreExecutedActionArtifactStore,
)
from fdai.delivery.reconciliation_observations import (
    RecordedExecutedActionObservation,
    StateStoreExecutedActionObservationStore,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord


class EffectReconciliationLineageMaterializer:
    """Append one complete lineage after independently observed terminal reconciliation."""

    def __init__(
        self,
        *,
        artifacts: StateStoreExecutedActionArtifactStore,
        proposals: StateStoreKineticActionProposalStore,
        observations: StateStoreExecutedActionObservationStore,
        projector: OperationalHypothesisLineageProjector,
    ) -> None:
        self._artifacts = artifacts
        self._proposals = proposals
        self._observations = observations
        self._projector = projector

    async def project(self, outcome: ReconciliationOutcome) -> bool:
        """Project exact terminal evidence, or decline legacy and incomplete episodes."""

        if not outcome.terminal:
            return False
        mutation_plan = outcome.request.plan
        operational_plan_id = mutation_plan.operational_plan_ref
        if operational_plan_id is None:
            return False
        try:
            action_id = str(UUID(outcome.correlation_id))
        except ValueError:
            return False
        if action_id != outcome.correlation_id:
            return False
        resolved_artifacts = await self._artifacts.resolve_by_action_id(action_id)
        if resolved_artifacts is None:
            return False
        kinetic_receipt, artifacts = resolved_artifacts
        if (
            artifacts.plan != mutation_plan
            or artifacts.active_release.ref() != outcome.request.evidence.ontology_release_ref
            or artifacts.action_type.name != mutation_plan.action_type_ref.name
            or artifacts.action_type.version != mutation_plan.action_type_ref.version
        ):
            raise ValueError("operational lineage kinetic artifacts do not match reconciliation")
        planning = await self._proposals.resolve_plan(operational_plan_id)
        if planning is None:
            return False
        operational_plan, proposal = planning
        if proposal.plan != mutation_plan:
            raise ValueError("operational lineage proposal does not match reconciliation plan")
        execution = await self._observations.resolve_record(
            action_id=outcome.correlation_id,
            plan_digest=mutation_plan.digest,
        )
        if execution is None:
            return False
        if (
            execution.correlation_id != outcome.correlation_id
            or execution.observation.evidence != outcome.request.evidence
            or execution.observation.observation_context != outcome.observation_context
        ):
            raise ValueError("operational lineage observation does not match reconciliation")
        if (
            operational_plan.context_cutoff is None
            or operational_plan.context_digest is None
            or execution.execution_mode == "unknown"
            or execution.execution_completed_at is None
        ):
            return False
        lineage = _build_lineage(
            plan=operational_plan,
            proposal=proposal,
            kinetic_receipt=kinetic_receipt,
            execution=execution,
            outcome=outcome,
        )
        await self._projector.project(lineage)
        return True


def _build_lineage(
    *,
    plan: OperationalPlan,
    proposal: KineticActionProposal,
    kinetic_receipt: KineticSafetyReceipt,
    execution: RecordedExecutedActionObservation,
    outcome: ReconciliationOutcome,
) -> OperationalHypothesisLineage:
    prospective = build_prospective_lineage_records(plan=plan, proposal=proposal)
    if prospective.action_option.properties["arguments"]["digest"] != (
        kinetic_receipt.arguments_digest
    ):
        raise ValueError("operational lineage argument digest changed after dispatch")
    expected_effects = prospective.expected_effects
    action_run_id = f"action-run:{outcome.correlation_id}"
    action_run = OntologyObjectRecord(
        id=action_run_id,
        object_type="ActionRun",
        properties={
            "id": action_run_id,
            "action_type_ref": outcome.request.plan.action_type_ref.name,
            "action_type_version": outcome.request.plan.action_type_ref.version,
            "target_ref": plan.target_resource_id,
            "status": execution.execution_outcome,
            "mode": execution.execution_mode,
            "idempotency_key": kinetic_receipt.action_idempotency_key,
            "started_at": kinetic_receipt.created_at,
            "ended_at": execution.execution_completed_at,
            "receipt_ref": execution.execution_receipt_ref or kinetic_receipt.receipt_id,
        },
    )
    observed_outcomes = tuple(
        _observed_outcome(
            expected_effect=expected_effect,
            action_run_id=action_run_id,
            execution=execution,
            outcome=outcome,
        )
        for expected_effect in expected_effects
    )
    return OperationalHypothesisLineage(
        decision_case=prospective.decision_case,
        action_option=prospective.action_option,
        expected_effects=expected_effects,
        action_run=action_run,
        observed_outcomes=observed_outcomes,
    )


def _observed_outcome(
    *,
    expected_effect: OntologyObjectRecord,
    action_run_id: str,
    execution: RecordedExecutedActionObservation,
    outcome: ReconciliationOutcome,
) -> OntologyObjectRecord:
    evidence = execution.observation.evidence
    metric = str(expected_effect.properties["metric"])
    values: dict[str, object] = {
        "metric": metric,
        "reconciliation_status": outcome.receipt.status.value,
        "evidence_refs": list(outcome.receipt.evidence_refs),
    }
    target_id = outcome.request.plan.targets[0].object_id
    observed_record = next(
        (record for record in evidence.records if record.object_id == target_id),
        None,
    )
    observed_value_present = False
    if observed_record is not None:
        observed_properties = observed_record.to_record().properties
        if metric in observed_properties:
            values["value"] = observed_properties[metric]
            observed_value_present = True
    scorable = (
        outcome.receipt.status in {ReconciliationStatus.MATCHED, ReconciliationStatus.MISMATCHED}
        and evidence.complete
        and not evidence.synthetic
        and not evidence.conflicts
        and not evidence.censoring_refs
        and observed_value_present
    )
    record_id = _lineage_id(
        "observed-outcome",
        outcome.reconciliation_id,
        expected_effect.id,
    )
    return OntologyObjectRecord(
        id=record_id,
        object_type="ObservedOutcome",
        properties={
            "id": record_id,
            "action_run_id": action_run_id,
            "expected_effect_ref": expected_effect.id,
            "verification": "independent",
            "recovery_status": (
                "not_required"
                if outcome.receipt.status is ReconciliationStatus.MATCHED
                else "required"
            ),
            "observed_values": values,
            "telemetry_complete": evidence.complete,
            "scorable": scorable,
            "observed_at": evidence.observed_at,
        },
    )


def _effect_values(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "confidence": effect.confidence,
        "window_seconds": effect.observation_window_seconds,
    }


def _direction(effect: ObjectiveEffect, baseline: ObjectiveEffect | None) -> str:
    if baseline is None:
        return "unknown"
    expected_midpoint = (effect.expected_min + effect.expected_max) / 2
    baseline_midpoint = (baseline.expected_min + baseline.expected_max) / 2
    if expected_midpoint > baseline_midpoint:
        return "increase"
    if expected_midpoint < baseline_midpoint:
        return "decrease"
    return "unchanged"


def _lineage_id(prefix: str, *parts: str) -> str:
    if re.fullmatch(r"[a-z][a-z0-9-]{0,63}", prefix) is None:
        raise ValueError("operational lineage id prefix is invalid")
    if not 1 <= len(parts) <= 8 or any(not part or len(part) > 1024 for part in parts):
        raise ValueError("operational lineage id parts MUST be non-empty and bounded")
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


__all__ = ["EffectReconciliationLineageMaterializer"]
