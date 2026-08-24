"""Focused tests for terminal effect-reconciliation lineage materialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

from fdai.delivery.operational_lineage import EffectReconciliationLineageMaterializer
from fdai.delivery.reconciliation_observations import RecordedExecutedActionObservation

from tests.core.operational_planning.test_twin_execution import NOW, _plan_and_release
from tests.delivery.test_kinetic_proposal import _inputs


@dataclass
class _Lookup:
    value: object

    async def resolve_by_action_id(self, action_id: str):
        assert action_id == "00000000-0000-0000-0000-000000000010"
        return self.value

    async def resolve_plan(self, plan_id: str):
        assert plan_id == self.value[0].plan_id
        return self.value

    async def resolve_record(self, *, action_id: str, plan_digest: str):
        assert action_id == "00000000-0000-0000-0000-000000000010"
        assert plan_digest == self.value.plan_digest
        return self.value


class _Projector:
    def __init__(self) -> None:
        self.lineage = None

    async def project(self, lineage) -> None:
        self.lineage = lineage


async def test_terminal_reconciliation_projects_complete_multi_effect_lineage() -> None:
    operational_plan, mutation_plan = _inputs()
    selected = next(
        option
        for option in operational_plan.decision_case.options
        if option.option_id == operational_plan.selection.selected_option_id
    )
    proposal = SimpleNamespace(plan=mutation_plan, arguments=lambda: {"replica_count": 3})
    receipt = SimpleNamespace(
        action_idempotency_key="example-action-1",
        arguments_digest=mutation_plan.arguments_digest,
        created_at=NOW,
        receipt_id="kinetic-safety:" + "a" * 64,
    )
    evidence = SimpleNamespace(
        records=(),
        complete=True,
        synthetic=False,
        conflicts=(),
        censoring_refs=(),
        observed_at=NOW + timedelta(minutes=5),
    )
    observation = SimpleNamespace(evidence=evidence, observation_context="context")
    execution = RecordedExecutedActionObservation(
        action_id="00000000-0000-0000-0000-000000000010",
        plan_digest=mutation_plan.digest,
        execution_outcome="succeeded",
        execution_mode="shadow",
        execution_completed_at=NOW + timedelta(minutes=1),
        execution_receipt_ref="receipt:executor:one",
        correlation_id="00000000-0000-0000-0000-000000000010",
        observation=observation,
    )
    artifacts = SimpleNamespace(
        plan=mutation_plan,
        active_release=SimpleNamespace(
            ref=lambda: "release-ref",
        ),
        action_type=SimpleNamespace(
            name=mutation_plan.action_type_ref.name,
            version=mutation_plan.action_type_ref.version,
        ),
    )
    outcome = SimpleNamespace(
        terminal=True,
        correlation_id="00000000-0000-0000-0000-000000000010",
        reconciliation_id="reconciliation:" + "b" * 64,
        observation_context="context",
        request=SimpleNamespace(
            plan=mutation_plan,
            evidence=SimpleNamespace(
                ontology_release_ref="release-ref",
                records=evidence.records,
                complete=evidence.complete,
                synthetic=evidence.synthetic,
                conflicts=evidence.conflicts,
                censoring_refs=evidence.censoring_refs,
                observed_at=evidence.observed_at,
            ),
        ),
        receipt=SimpleNamespace(
            status=SimpleNamespace(value="matched"),
            evidence_refs=("evidence:one",),
        ),
    )
    outcome.receipt.status = __import__(
        "fdai.core.ontology_platform.kinetics", fromlist=["ReconciliationStatus"]
    ).ReconciliationStatus.MATCHED
    execution = RecordedExecutedActionObservation(
        action_id=execution.action_id,
        plan_digest=execution.plan_digest,
        execution_outcome=execution.execution_outcome,
        execution_mode=execution.execution_mode,
        execution_completed_at=execution.execution_completed_at,
        execution_receipt_ref=execution.execution_receipt_ref,
        correlation_id=execution.correlation_id,
        observation=SimpleNamespace(
            evidence=outcome.request.evidence,
            observation_context="context",
        ),
    )
    projector = _Projector()
    materializer = EffectReconciliationLineageMaterializer(
        artifacts=_Lookup((receipt, artifacts)),
        proposals=_Lookup((operational_plan, proposal)),
        observations=_Lookup(execution),
        projector=projector,
    )

    assert await materializer.project(outcome) is True
    lineage = projector.lineage
    assert lineage is not None
    assert lineage.decision_case.properties["target_ref"] == operational_plan.target_resource_id
    assert lineage.action_option.properties["arguments"] == {
        "digest": mutation_plan.arguments_digest,
        "redacted": True,
    }
    assert lineage.action_run.properties["status"] == "succeeded"
    assert lineage.action_run.properties["mode"] == "shadow"
    assert len(lineage.expected_effects) == len(selected.effects)
    assert len(lineage.observed_outcomes) == len(selected.effects)
    assert all(
        item.properties["verification"] == "independent" for item in lineage.observed_outcomes
    )
    assert all(item.properties["scorable"] is False for item in lineage.observed_outcomes)


async def test_legacy_plan_without_context_lineage_is_not_projected() -> None:
    plan, _target, _release = _plan_and_release()
    legacy = plan.__class__(
        plan_id=plan.plan_id,
        process_id=plan.process_id,
        target_resource_id=plan.target_resource_id,
        logic_release_digest=plan.logic_release_digest,
        decision_case=plan.decision_case,
        selection=plan.selection,
        assessments=plan.assessments,
        complete=plan.complete,
        reason=plan.reason,
    )
    assert legacy.context_cutoff is None
