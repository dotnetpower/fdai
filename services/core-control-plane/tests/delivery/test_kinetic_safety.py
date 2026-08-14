"""Focused tests for exact pre-dispatch kinetic safety persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.decision_case import ObjectiveEffect
from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.ontology_platform.reconciliation_binding import ResolvedReconciliationArtifacts
from fdai.core.operational_planning import (
    ConstraintEvaluation,
    ConstraintStatus,
    OperationalPlan,
    PlanCandidate,
    PlanningRequest,
    SimulationReceipt,
    SimulationStatus,
    SpecialistContribution,
    build_operational_plan,
)
from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.delivery.kinetic_safety import ExistingProposalKineticSafetyWriter
from fdai.delivery.reconciliation_artifacts import StateStoreExecutedActionArtifactStore
from fdai.shared.contracts.models import Action, OntologyActionType, OntologyRelease
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.ontology_platform.test_reconciliation import _fixture
from tests.core.operational_planning.test_twin_execution import NOW, _context
from tests.delivery.test_reconciliation_request import _action


def _exact_inputs() -> tuple[
    OperationalPlan,
    MutationPlan,
    Action,
    OntologyActionType,
    OntologyRelease,
]:
    release, target, base_plan, action_type = _fixture()
    context = replace(_context(), target_resource_id=target.id)
    effect = ObjectiveEffect(
        "reliability",
        0.8,
        0.9,
        "replicas",
        2.0,
        3.0,
        300,
    )
    contribution = SpecialistContribution(
        "Freyr",
        "capacity",
        "scale",
        NOW,
        0.9,
        ("forecast:1",),
        ("logic-invocation:" + "c" * 64,),
    )
    simulation = SimulationReceipt(
        "simulation:1",
        "capacity:scale",
        context.snapshot_id,
        "logic-invocation:" + "c" * 64,
        SimulationStatus.SUCCEEDED,
        NOW,
        NOW,
        ("twin:1",),
        (effect,),
    )
    candidate = PlanCandidate(
        "capacity:scale",
        action_type.name,
        (effect,),
        (contribution,),
        (ConstraintEvaluation("slo", ConstraintStatus.PASSED, 3, "verified", ("slo:1",)),),
        (simulation,),
        ("forecast:1", "twin:1"),
    )
    operational_plan = build_operational_plan(
        PlanningRequest(
            "process-example",
            "correlation-example",
            release.digest,
            context,
            (ObjectiveEffect("reliability", -0.8, 0.9, "replicas", 0.0, 2.0, 300),),
            ("reliability",),
            (candidate,),
            (("reliability", 1.0),),
            NOW,
        )
    )
    target_record = OntologyObjectRecord(
        id=target.id,
        object_type=target.object_type,
        properties={},
        revision=target.revision,
        type_ref=target.type_ref,
    )
    plan = build_mutation_plan(
        action_type_ref=base_plan.action_type_ref,
        planner_ref=base_plan.planner_ref,
        targets=(target_record,),
        effects=base_plan.effects,
        rollback_effects=base_plan.rollback_effects,
        expected_effects=base_plan.expected_effects,
        created_at=base_plan.created_at,
        max_affected_objects=base_plan.max_affected_objects or 1,
        schema_version="2.0.0",
        arguments_digest=base_plan.arguments_digest,
        argument_bindings=base_plan.argument_bindings,
        read_set_receipt_digests=base_plan.read_set_receipt_digests,
        criterion_receipt_digests=base_plan.criterion_receipt_digests,
        transaction_mode=base_plan.transaction_mode,
        lock_scope=base_plan.lock_scope,
        lock_keys=base_plan.lock_keys,
        irreversible=base_plan.irreversible,
        operational_plan_ref=operational_plan.plan_id,
    )
    action = _action(ResolvedReconciliationArtifacts(plan, action_type, release))
    return operational_plan, plan, action, action_type, release


def _writer(
    state_store: InMemoryStateStore,
) -> tuple[
    ExistingProposalKineticSafetyWriter,
    StateStoreKineticActionProposalStore,
    StateStoreExecutedActionArtifactStore,
]:
    _operational_plan, _plan, _action_value, action_type, release = _exact_inputs()
    proposal_store = StateStoreKineticActionProposalStore(store=state_store)
    artifact_store = StateStoreExecutedActionArtifactStore(store=state_store)
    writer = ExistingProposalKineticSafetyWriter(
        proposal_store=proposal_store,
        artifact_store=artifact_store,
        action_types_by_name={action_type.name: action_type},
        active_release=release,
    )
    return writer, proposal_store, artifact_store


async def test_missing_proposal_preserves_legacy_path_without_artifact() -> None:
    state_store = InMemoryStateStore()
    writer, _proposal_store, artifact_store = _writer(state_store)
    _operational_plan, _plan, action, _action_type_value, _release = _exact_inputs()

    receipt_id = await writer.persist(
        action=action,
        correlation_id="correlation:missing",
    )

    assert receipt_id is None
    assert await artifact_store.resolve(action) is None


async def test_existing_proposal_persists_exact_receipt_before_dispatch() -> None:
    state_store = InMemoryStateStore()
    writer, proposal_store, artifact_store = _writer(state_store)
    operational_plan, plan, action, action_type, _release = _exact_inputs()
    proposal = await proposal_store.commit(
        operational_plan=operational_plan,
        mutation_plan=plan,
        arguments={},
        created_at=plan.created_at + timedelta(seconds=1),
    )
    action = action.model_copy(update={"created_at": plan.created_at + timedelta(seconds=2)})

    receipt_id = await writer.persist(
        action=action,
        correlation_id=proposal.correlation_id,
    )
    resolved = await artifact_store.resolve(action)

    assert receipt_id is not None
    assert receipt_id.startswith("kinetic-safety:")
    assert resolved is not None
    assert resolved.plan == proposal.plan
    assert resolved.action_type == action_type


async def test_present_proposal_rejects_substituted_action() -> None:
    state_store = InMemoryStateStore()
    writer, proposal_store, artifact_store = _writer(state_store)
    operational_plan, plan, action, _action_type_value, _release = _exact_inputs()
    proposal = await proposal_store.commit(
        operational_plan=operational_plan,
        mutation_plan=plan,
        arguments={},
        created_at=plan.created_at + timedelta(seconds=1),
    )
    action = action.model_copy(
        update={
            "created_at": plan.created_at + timedelta(seconds=2),
            "target_resource_ref": "resource:substituted",
        }
    )

    with pytest.raises(ValueError, match="do not match the executed Action"):
        await writer.persist(action=action, correlation_id=proposal.correlation_id)

    assert await artifact_store.resolve(action) is None


async def test_proposal_created_after_action_is_rejected() -> None:
    state_store = InMemoryStateStore()
    writer, proposal_store, artifact_store = _writer(state_store)
    operational_plan, plan, action, _action_type_value, _release = _exact_inputs()
    proposal = await proposal_store.commit(
        operational_plan=operational_plan,
        mutation_plan=plan,
        arguments={},
        created_at=plan.created_at + timedelta(seconds=1),
    )
    action = action.model_copy(update={"created_at": plan.created_at})

    with pytest.raises(ValueError, match="before its Action"):
        await writer.persist(action=action, correlation_id=proposal.correlation_id)

    assert await artifact_store.resolve(action) is None
