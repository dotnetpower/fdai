"""Adversarial tests for durable exact kinetic proposal production."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.operational_planning import KineticActionProposal, OperationalPlan
from fdai.delivery.kinetic_proposal import (
    KineticActionProposalConflictError,
    StateStoreKineticActionProposalStore,
)
from fdai.shared.contracts.models import OntologyDeclarationKind
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_planning.test_kinetic_proposal import _plan, _rebuild
from tests.core.operational_planning.test_twin_execution import _plan_and_release


def _inputs(arguments: dict[str, object] | None = None) -> tuple[OperationalPlan, MutationPlan]:
    operational_plan, _target, release = _plan_and_release()
    base = _plan(arguments)
    base_target = base.targets[0]
    target = OntologyObjectRecord(
        id=operational_plan.target_resource_id,
        object_type=base_target.type_ref.name,
        properties={},
        revision=base_target.revision,
        type_ref=base_target.type_ref,
    )
    mutation_plan = build_mutation_plan(
        action_type_ref=release.type_ref(OntologyDeclarationKind.ACTION, "ops.scale-out"),
        planner_ref=base.planner_ref,
        targets=(target,),
        effects=base.effects,
        rollback_effects=base.rollback_effects,
        expected_effects=base.expected_effects,
        created_at=base.created_at,
        max_affected_objects=base.max_affected_objects or 1,
        schema_version="2.0.0",
        arguments_digest=base.arguments_digest,
        argument_bindings=base.argument_bindings,
        read_set_receipt_digests=base.read_set_receipt_digests,
        criterion_receipt_digests=base.criterion_receipt_digests,
        transaction_mode=base.transaction_mode,
        lock_scope=base.lock_scope,
        lock_keys=(f"ontology-target:{target.id}",),
        irreversible=base.irreversible,
        operational_plan_ref=operational_plan.plan_id,
    )
    return operational_plan, mutation_plan


async def test_commit_and_resolve_existing_exact_v2_plan() -> None:
    operational_plan, mutation_plan = _inputs({"replica_count": 3})
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={"replica_count": 3},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )

    assert await adapter.resolve(operational_plan) == proposal
    assert proposal.plan == mutation_plan
    assert proposal.plan.operational_plan_ref == operational_plan.plan_id
    assert proposal.plan.planner_ref != operational_plan.plan_id


async def test_resolve_by_exact_correlation_uses_committed_proposal() -> None:
    operational_plan, mutation_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())
    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )

    assert await adapter.resolve_by_correlation(proposal.correlation_id) == proposal


async def test_missing_correlation_declines_without_plan_synthesis() -> None:
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    assert await adapter.resolve_by_correlation("correlation:missing") is None


async def test_correlation_conflict_is_rejected_before_second_proposal_write() -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)
    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    with pytest.raises(KineticActionProposalConflictError, match="correlation identity"):
        await adapter._claim_correlation_index(
            correlation_id=proposal.correlation_id,
            operational_plan_id="operational-plan:" + "f" * 64,
        )

    assert await adapter.resolve_by_correlation(proposal.correlation_id) == proposal


async def test_orphaned_correlation_index_fails_closed() -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)
    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    await state_store.write_state(
        f"operational-planning:kinetic-proposal:{operational_plan.plan_id}",
        {},
    )

    with pytest.raises(RuntimeError, match="operational plan is malformed"):
        await adapter.resolve_by_correlation(proposal.correlation_id)


async def test_identical_commit_replay_is_one_durable_record() -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)

    first = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    replay = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    records = await state_store.read_states("operational-planning:kinetic-proposal:", limit=10)

    assert replay == first
    assert len(records) == 1


async def test_same_plan_replay_with_different_timestamp_conflicts() -> None:
    operational_plan, mutation_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())
    await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )

    with pytest.raises(KineticActionProposalConflictError):
        await adapter.commit(
            operational_plan=operational_plan,
            mutation_plan=mutation_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=2),
        )


async def test_missing_record_declines_without_plan_synthesis() -> None:
    operational_plan, _mutation_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    assert await adapter.resolve(operational_plan) is None


async def test_incomplete_operational_plan_is_rejected_before_write() -> None:
    operational_plan, mutation_plan = _inputs()
    incomplete = replace(operational_plan, complete=False, reason="incomplete evidence")
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    with pytest.raises(ValueError, match="complete operational plan"):
        await adapter.commit(
            operational_plan=incomplete,
            mutation_plan=mutation_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    "mutation_plan",
    (
        _rebuild(_inputs()[1], operational_plan_ref=None),
        _rebuild(_inputs()[1], operational_plan_ref="operational-plan:" + "f" * 64),
        _inputs()[1].model_copy(update={"schema_version": "1.0.0"}),
    ),
)
async def test_missing_substituted_or_legacy_plan_lineage_is_rejected(
    mutation_plan: MutationPlan,
) -> None:
    operational_plan, _exact_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    with pytest.raises(ValueError, match="do not match operational selection"):
        await adapter.commit(
            operational_plan=operational_plan,
            mutation_plan=mutation_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )


async def test_action_type_and_target_substitution_is_rejected() -> None:
    operational_plan, mutation_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    substituted_type = mutation_plan.action_type_ref.model_copy(update={"name": "ops.stop"})
    substituted_plan = mutation_plan.model_copy(update={"action_type_ref": substituted_type})
    with pytest.raises(ValueError, match="do not match operational selection"):
        await adapter.commit(
            operational_plan=operational_plan,
            mutation_plan=substituted_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )

    substituted_target = replace(operational_plan, target_resource_id="resource:substituted")
    with pytest.raises(ValueError, match="identity does not match"):
        await adapter.commit(
            operational_plan=substituted_target,
            mutation_plan=mutation_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )


async def test_same_plan_id_with_different_full_content_conflicts() -> None:
    operational_plan, mutation_plan = _inputs()
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())
    await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    substituted_case = replace(
        operational_plan.decision_case,
        correlation_id="correlation:substituted",
    )
    substituted = replace(operational_plan, decision_case=substituted_case)

    with pytest.raises(KineticActionProposalConflictError):
        await adapter.commit(
            operational_plan=substituted,
            mutation_plan=mutation_plan,
            arguments={},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )


async def test_corrupted_durable_record_fails_closed() -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)
    await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    key = f"operational-planning:kinetic-proposal:{operational_plan.plan_id}"
    stored = await state_store.read_state(key)
    assert stored is not None
    corrupted = dict(stored)
    corrupted["operational_plan_id"] = "operational-plan:" + "e" * 64
    await state_store.write_state(key, corrupted)

    with pytest.raises(RuntimeError, match="identity is malformed"):
        await adapter.resolve(operational_plan)


@pytest.mark.parametrize(
    "proposal_update",
    (
        {"correlation_id": "correlation:substituted"},
        {"process_id": "process-substituted"},
        {"selected_option_id": "option-substituted"},
    ),
)
async def test_internally_valid_cross_record_lineage_substitution_fails_closed(
    proposal_update: dict[str, str],
) -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)
    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    substituted = KineticActionProposal.create(
        correlation_id=proposal_update.get("correlation_id", proposal.correlation_id),
        process_id=proposal_update.get("process_id", proposal.process_id),
        operational_plan_id=proposal.operational_plan_id,
        selected_option_id=proposal_update.get(
            "selected_option_id",
            proposal.selected_option_id,
        ),
        plan=proposal.plan,
        target_resource_ref=proposal.target_resource_ref,
        arguments=proposal.arguments(),
        created_at=proposal.created_at,
    )
    key = f"operational-planning:kinetic-proposal:{operational_plan.plan_id}"
    raw = dict((await state_store.read_state(key)) or {})
    raw["proposal"] = substituted.model_dump(mode="json")
    await state_store.write_state(key, raw)

    with pytest.raises(RuntimeError, match="does not match its operational plan"):
        await adapter.resolve_by_correlation(proposal.correlation_id)


async def test_substituted_operational_plan_body_fails_closed() -> None:
    operational_plan, mutation_plan = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreKineticActionProposalStore(store=state_store)
    proposal = await adapter.commit(
        operational_plan=operational_plan,
        mutation_plan=mutation_plan,
        arguments={},
        created_at=mutation_plan.created_at + timedelta(seconds=1),
    )
    key = f"operational-planning:kinetic-proposal:{operational_plan.plan_id}"
    raw = dict((await state_store.read_state(key)) or {})
    stored_plan = dict(raw["operational_plan"])
    stored_plan["process_id"] = "process-substituted"
    raw["operational_plan"] = stored_plan
    await state_store.write_state(key, raw)

    with pytest.raises(RuntimeError, match="operational plan is malformed"):
        await adapter.resolve_by_correlation(proposal.correlation_id)


async def test_argument_mismatch_is_rejected_by_exact_proposal_contract() -> None:
    operational_plan, mutation_plan = _inputs({"replica_count": 3})
    adapter = StateStoreKineticActionProposalStore(store=InMemoryStateStore())

    with pytest.raises(ValueError, match="arguments do not match"):
        await adapter.commit(
            operational_plan=operational_plan,
            mutation_plan=mutation_plan,
            arguments={"replica_count": 4},
            created_at=mutation_plan.created_at + timedelta(seconds=1),
        )
