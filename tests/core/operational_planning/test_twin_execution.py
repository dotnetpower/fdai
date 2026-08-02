from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fdai.core.assurance_twin.effect_model import EffectModel, EffectModelStatus
from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.core.operational_planning import (
    AssuranceTwinPlanningSimulator,
    CandidateAssessment,
    CandidateDisposition,
    ConstraintEvaluation,
    ConstraintStatus,
    OperationalPlan,
    PlanCandidate,
    PlanningRequest,
    SimulationReceipt,
    SimulationStatus,
    SpecialistContribution,
    build_operational_plan,
    close_operational_plan,
    compile_selected_mutation_plan,
)
from fdai.shared.contracts.models import (
    Autonomy,
    CausalEvidenceGrade,
    Mode,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _context() -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id="a" * 64,
        target_resource_id="resource-example",
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", "1.0.0"),),
        service_ids=(),
        workload_ids=(),
        objective_ids=("reliability",),
        service_objective_ids=("reliability",),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=("slo",),
        ownership_ids=(),
        dependency_ids=(),
        source_freshness=(),
        evidence_links=(),
        evidence_paths=(),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def _model(status: EffectModelStatus, *, bias: float = 0.0) -> EffectModel:
    return EffectModel(
        model_id=f"model-{status.value}",
        version="1.0.0",
        revision=1,
        action_type_id="ops.scale-out",
        metric="availability",
        status=status,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="b" * 64,
        learned_at=NOW - timedelta(days=2),
        learned_through=NOW - timedelta(days=1),
        sample_count=30,
        bias_correction=bias,
        interval_radius=0.01,
    )


class _Models:
    def __init__(self, active: EffectModel | None, challenger: EffectModel | None) -> None:
        self.active = active
        self.challenger = challenger

    async def get(self, *, status, action_type_id, metric):
        assert action_type_id == "ops.scale-out"
        assert metric == "availability"
        return self.active if status is EffectModelStatus.ACTIVE else self.challenger


class _MetricModels:
    def __init__(self, active_by_metric: dict[str, EffectModel]) -> None:
        self._active_by_metric = active_by_metric

    async def get(self, *, status, action_type_id, metric):
        assert action_type_id == "ops.scale-out"
        return self._active_by_metric.get(metric) if status is EffectModelStatus.ACTIVE else None


class _Verifier:
    def verify(self, model: EffectModel) -> bool:
        return model.evidence_grade in {
            CausalEvidenceGrade.QUASI_EXPERIMENTAL,
            CausalEvidenceGrade.INTERVENTIONAL,
        }


async def test_twin_simulation_uses_active_model_and_flags_divergence() -> None:
    ticks = iter((NOW, NOW + timedelta(seconds=1)))
    simulator = AssuranceTwinPlanningSimulator(
        model_reader=_Models(
            _model(EffectModelStatus.ACTIVE), _model(EffectModelStatus.CHALLENGER, bias=0.2)
        ),
        causal_evidence_verifier=_Verifier(),
        divergence_threshold=0.1,
        clock=lambda: next(ticks),
    )

    receipt = await simulator.simulate(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(ObjectiveEffect("reliability", 0.8, 0.9, "availability", 0.9, 1.0, 300),),
        observed_at=NOW,
    )

    assert receipt.status is SimulationStatus.SUCCEEDED
    assert receipt.requires_review is True
    assert receipt.reason == "model_divergence"
    assert receipt.predicted_effects[0].expected_min == pytest.approx(0.90)


async def test_twin_simulation_without_verified_active_model_is_unscorable() -> None:
    simulator = AssuranceTwinPlanningSimulator(
        model_reader=_Models(None, None),
        causal_evidence_verifier=_Verifier(),
        clock=lambda: NOW,
    )

    receipt = await simulator.simulate(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(ObjectiveEffect("reliability", 0.8, 0.9, "availability", 0.9, 1.0, 300),),
        observed_at=NOW,
    )

    assert receipt.status is SimulationStatus.UNSCORABLE
    assert receipt.requires_review is True


async def test_twin_simulation_is_canonical_across_effect_order() -> None:
    reliability = ObjectiveEffect("reliability", 0.8, 0.9, "availability", 0.9, 1.0, 300)
    cost = ObjectiveEffect("cost", -0.2, 0.8, "usd", 10.0, 20.0, 300)
    models = _MetricModels(
        {
            "availability": _model(EffectModelStatus.ACTIVE),
            "usd": replace(
                _model(EffectModelStatus.ACTIVE),
                model_id="model-active-usd",
                metric="usd",
                bias_correction=-1.0,
            ),
        }
    )
    simulator = AssuranceTwinPlanningSimulator(
        model_reader=models,
        causal_evidence_verifier=_Verifier(),
        clock=lambda: NOW,
    )

    first = await simulator.simulate(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(reliability, cost),
        observed_at=NOW,
    )
    reordered = await simulator.simulate(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(cost, reliability),
        observed_at=NOW,
    )

    assert reordered == first


def _plan_and_release() -> tuple[OperationalPlan, OntologyObjectRecord, object]:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    action_type = OntologyActionType(
        schema_version="1.0.0",
        name="ops.scale-out",
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
    )
    release = build_ontology_release(object_types=(object_type,), action_types=(action_type,))
    target = OntologyObjectRecord(
        id="resource-example",
        object_type="Workload",
        properties={"id": "resource-example"},
        revision=1,
        type_ref=release.type_ref(OntologyDeclarationKind.OBJECT, "Workload"),
    )
    contribution = SpecialistContribution(
        "Freyr",
        "capacity",
        "scale_up",
        NOW,
        0.9,
        ("forecast:1",),
        ("logic-invocation:" + "c" * 64,),
    )
    simulation = SimulationReceipt(
        "simulation:1",
        "capacity:scale_up",
        _context().snapshot_id,
        "logic-invocation:" + "c" * 64,
        SimulationStatus.SUCCEEDED,
        NOW,
        NOW,
        ("twin:1",),
        (ObjectiveEffect("reliability", 0.8, 0.9, "availability", 0.9, 1.0, 300),),
    )
    candidate = PlanCandidate(
        "capacity:scale_up",
        "ops.scale-out",
        simulation.predicted_effects,
        (contribution,),
        (ConstraintEvaluation("slo", ConstraintStatus.PASSED, 3, "verified", ("slo:1",)),),
        (simulation,),
        ("forecast:1", "twin:1"),
    )
    plan = build_operational_plan(
        PlanningRequest(
            "process-example",
            "correlation-example",
            release.digest,
            _context(),
            (ObjectiveEffect("reliability", -0.8, 0.9, "availability", 0.0, 0.5, 300),),
            ("reliability",),
            (candidate,),
            (("reliability", 1.0),),
            NOW,
        )
    )
    return plan, target, release


def _response_outcome(
    *,
    prediction_id: str,
    label: ResponseOutcomeLabel,
    observed_value: float,
) -> ResponseOutcome:
    action_id = uuid4()
    return ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid4(),
        idempotency_key=f"response-outcome:{action_id}",
        action_id=action_id,
        event_id=uuid4(),
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        prediction_id=prediction_id,
        metric="availability",
        expected_min=0.9,
        expected_max=1.0,
        observed_value=observed_value,
        predicted_at=NOW,
        observation_deadline=NOW + timedelta(minutes=5),
        observed_at=NOW + timedelta(minutes=4),
        label=label,
        verification_status=ResponseVerificationStatus.VERIFIED,
        verification_reason="within_expected_range",
        execution_mode=Mode.ENFORCE,
        execution_outcome="success",
        decision="hil",
        rollback_succeeded=None,
        evidence_refs=("metric:1",),
        recorded_at=NOW + timedelta(minutes=5),
    )


def test_selected_plan_compiles_exact_mutation_plan_and_closes_outcome() -> None:
    plan, target, release = _plan_and_release()
    mutation = compile_selected_mutation_plan(
        plan=plan,
        target=target,
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
        command_ref="provider.scale-out",
        rollback_command_ref="provider.scale-in",
        created_at=NOW,
        max_affected_objects=1,
    )
    action_id = uuid4()
    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid4(),
        idempotency_key=f"response-outcome:{action_id}",
        action_id=action_id,
        event_id=uuid4(),
        action_type_id="ops.scale-out",
        target_digest="d" * 64,
        prediction_id=mutation.plan_id,
        metric="availability",
        expected_min=0.9,
        expected_max=1.0,
        observed_value=0.99,
        predicted_at=NOW,
        observation_deadline=NOW + timedelta(minutes=5),
        observed_at=NOW + timedelta(minutes=4),
        label=ResponseOutcomeLabel.VERIFIED,
        verification_status=ResponseVerificationStatus.VERIFIED,
        verification_reason="within_expected_range",
        execution_mode=Mode.ENFORCE,
        execution_outcome="success",
        decision="hil",
        rollback_succeeded=None,
        evidence_refs=("metric:1",),
        recorded_at=NOW + timedelta(minutes=5),
    )

    closure = close_operational_plan(plan, mutation, outcome)

    assert mutation.action_type_ref.name == "ops.scale-out"
    assert mutation.targets[0].revision == 1
    assert mutation.expected_effects[0].property_name == "availability"
    assert closure.effect_verified is True


def test_mutation_compiler_rejects_action_mismatch_or_incomplete_plan() -> None:
    plan, target, release = _plan_and_release()
    mismatch = release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out").model_copy(
        update={"name": "ops.scale-in"},
    )
    values = dict(
        plan=plan,
        target=target,
        command_ref="provider.scale-out",
        rollback_command_ref="provider.scale-in",
        created_at=NOW,
        max_affected_objects=1,
    )

    with pytest.raises(ValueError, match="does not match"):
        compile_selected_mutation_plan(action_type_ref=mismatch, **values)
    incomplete = replace(
        plan,
        complete=False,
        assessments=(
            CandidateAssessment(
                "capacity:scale_up",
                CandidateDisposition.INELIGIBLE,
                ("simulation_unavailable",),
            ),
        ),
    )
    with pytest.raises(ValueError, match="no complete selection"):
        compile_selected_mutation_plan(
            action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
            **{**values, "plan": incomplete},
        )


def test_outcome_closure_requires_exact_mutation_prediction() -> None:
    plan, target, release = _plan_and_release()
    mutation = compile_selected_mutation_plan(
        plan=plan,
        target=target,
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
        command_ref="provider.scale-out",
        rollback_command_ref="provider.scale-in",
        created_at=NOW,
        max_affected_objects=1,
    )
    outcome = _response_outcome(
        prediction_id="mutation-plan:" + "f" * 64,
        label=ResponseOutcomeLabel.VERIFIED,
        observed_value=0.99,
    )

    with pytest.raises(ValueError, match="does not cite"):
        close_operational_plan(plan, mutation, outcome)


def test_partial_failure_keeps_rollback_and_is_not_reusable() -> None:
    plan, target, release = _plan_and_release()
    mutation = compile_selected_mutation_plan(
        plan=plan,
        target=target,
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
        command_ref="provider.scale-out",
        rollback_command_ref="provider.scale-in",
        created_at=NOW,
        max_affected_objects=1,
    )
    action_id = uuid4()
    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid4(),
        idempotency_key=f"response-outcome:{action_id}",
        action_id=action_id,
        event_id=uuid4(),
        action_type_id="ops.scale-out",
        target_digest="e" * 64,
        prediction_id=mutation.plan_id,
        metric="availability",
        expected_min=0.9,
        expected_max=1.0,
        observed_value=0.5,
        predicted_at=NOW,
        observation_deadline=NOW + timedelta(minutes=5),
        observed_at=NOW + timedelta(minutes=4),
        label=ResponseOutcomeLabel.MISMATCH,
        verification_status=ResponseVerificationStatus.MISMATCH,
        verification_reason="outside_expected_range",
        execution_mode=Mode.ENFORCE,
        execution_outcome="rolled_back",
        decision="hil",
        rollback_succeeded=True,
        evidence_refs=("metric:failure", "rollback:verified"),
        recorded_at=NOW + timedelta(minutes=5),
    )

    closure = close_operational_plan(plan, mutation, outcome)

    assert mutation.rollback_effects[0].command_ref == "provider.scale-in"
    assert closure.effect_verified is False
    assert closure.reusable is False


def test_a0_planning_produces_proposal_without_execution_authority() -> None:
    plan, target, release = _plan_and_release()

    mutation = compile_selected_mutation_plan(
        plan=plan,
        target=target,
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
        command_ref="provider.scale-out",
        rollback_command_ref="provider.scale-in",
        created_at=NOW,
        max_affected_objects=1,
    )

    assert mutation.planner_ref == plan.plan_id
    assert not hasattr(mutation, "approval")
    assert not hasattr(mutation, "executor_identity")
