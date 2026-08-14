"""Adversarial tests for durable pre-dispatch kinetic artifacts."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.ontology_platform.reconciliation_binding import ResolvedReconciliationArtifacts
from fdai.delivery.reconciliation_artifacts import (
    KineticSafetyArtifactConflictError,
    KineticSafetyReceipt,
    StateStoreExecutedActionArtifactStore,
)
from fdai.shared.contracts.models import (
    Action,
    Mode,
    OntologyActionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from pydantic import ValidationError

from tests.core.ontology_platform.test_reconciliation import _fixture
from tests.delivery.test_reconciliation_request import _action


def _inputs() -> tuple[Action, MutationPlan, OntologyActionType, OntologyRelease]:
    release, _target, plan, action_type = _fixture()
    action = _action(ResolvedReconciliationArtifacts(plan, action_type, release))
    return action, plan, action_type, release


def _rebuild_plan(
    plan: MutationPlan,
    *,
    revision: int | None = None,
    created_delta: int = 0,
) -> MutationPlan:
    target = plan.targets[0]
    target_record = OntologyObjectRecord(
        id=target.object_id,
        object_type=target.type_ref.name,
        properties={},
        revision=revision or target.revision,
        type_ref=target.type_ref,
    )
    return build_mutation_plan(
        action_type_ref=plan.action_type_ref,
        planner_ref=plan.planner_ref,
        targets=(target_record,),
        effects=plan.effects,
        rollback_effects=plan.rollback_effects,
        expected_effects=plan.expected_effects,
        created_at=plan.created_at + timedelta(seconds=created_delta),
        max_affected_objects=plan.max_affected_objects or 1,
        schema_version=plan.schema_version,
        arguments_digest=plan.arguments_digest,
        argument_bindings=plan.argument_bindings,
        read_set_receipt_digests=plan.read_set_receipt_digests,
        criterion_receipt_digests=plan.criterion_receipt_digests,
        transaction_mode=plan.transaction_mode,
        lock_scope=plan.lock_scope,
        lock_keys=plan.lock_keys,
        irreversible=plan.irreversible,
    )


async def test_store_and_resolve_exact_pre_dispatch_artifacts() -> None:
    action, plan, action_type, release = _inputs()
    adapter = StateStoreExecutedActionArtifactStore(store=InMemoryStateStore())

    receipt = await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    resolved = await adapter.resolve(action)

    assert receipt.action_id == action.action_id
    assert resolved is not None
    assert resolved.plan == plan
    assert resolved.action_type == action_type
    assert resolved.active_release == release


async def test_missing_action_record_declines_without_plan_synthesis() -> None:
    action, _, _, _ = _inputs()
    adapter = StateStoreExecutedActionArtifactStore(store=InMemoryStateStore())

    assert await adapter.resolve(action) is None


async def test_identical_store_replay_is_one_durable_record() -> None:
    action, plan, action_type, release = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreExecutedActionArtifactStore(store=state_store)

    first = await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    replayed = await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    records = await state_store.read_states("ontology:kinetic-safety-artifact:", limit=10)

    assert replayed == first
    assert len(records) == 1


async def test_same_action_id_with_different_plan_conflicts() -> None:
    action, plan, action_type, release = _inputs()
    adapter = StateStoreExecutedActionArtifactStore(store=InMemoryStateStore())
    await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    revised_plan = _rebuild_plan(plan, revision=2)

    with pytest.raises(KineticSafetyArtifactConflictError):
        await adapter.store(
            action=action,
            plan=revised_plan,
            action_type=action_type,
            active_release=release,
        )


def test_v1_plan_is_rejected_instead_of_upgraded() -> None:
    action, plan, action_type, release = _inputs()
    legacy = plan.model_copy(update={"schema_version": "1.0.0"})

    with pytest.raises(ValueError, match="existing semantic V2 plan"):
        KineticSafetyReceipt.seal(
            action=action,
            plan=legacy,
            action_type=action_type,
            active_release=release,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("action_type_ref", None),
        ("params", {"unexpected": True}),
        ("target_resource_ref", "resource:substituted"),
    ),
)
def test_action_identity_drift_is_rejected(field: str, value: object) -> None:
    action, plan, action_type, release = _inputs()
    drifted = action.model_copy(update={field: value})

    with pytest.raises(ValueError, match="exact ActionType ref|do not match"):
        KineticSafetyReceipt.seal(
            action=drifted,
            plan=plan,
            action_type=action_type,
            active_release=release,
        )


def test_action_type_ref_version_drift_is_rejected() -> None:
    action, plan, action_type, release = _inputs()
    assert action.action_type_ref is not None
    drifted_ref = action.action_type_ref.model_copy(update={"version": "9.9.9"})
    drifted = action.model_copy(update={"action_type_ref": drifted_ref})

    with pytest.raises(ValueError, match="do not match"):
        KineticSafetyReceipt.seal(
            action=drifted,
            plan=plan,
            action_type=action_type,
            active_release=release,
        )


def test_action_type_body_substitution_is_rejected() -> None:
    action, plan, action_type, release = _inputs()
    substituted = action_type.model_copy(update={"description": "substituted"})

    with pytest.raises(ValueError, match="content does not match the active release"):
        KineticSafetyReceipt.seal(
            action=action,
            plan=plan,
            action_type=substituted,
            active_release=release,
        )


def test_plan_created_after_action_is_rejected() -> None:
    action, plan, action_type, release = _inputs()
    later = _rebuild_plan(plan, created_delta=1)

    with pytest.raises(ValueError, match="before its Action"):
        KineticSafetyReceipt.seal(
            action=action,
            plan=later,
            action_type=action_type,
            active_release=release,
        )


async def test_corrupted_durable_receipt_fails_closed() -> None:
    action, plan, action_type, release = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreExecutedActionArtifactStore(store=state_store)
    await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    key = f"ontology:kinetic-safety-artifact:{action.action_id}"
    raw = dict((await state_store.read_state(key)) or {})
    receipt = dict(raw["receipt"])
    receipt["plan_digest"] = "sha256:" + "0" * 64
    raw["receipt"] = receipt
    await state_store.write_state(key, raw)

    with pytest.raises(RuntimeError, match="failed validation"):
        await adapter.resolve(action)


async def test_resolve_rejects_substituted_action_body() -> None:
    action, plan, action_type, release = _inputs()
    adapter = StateStoreExecutedActionArtifactStore(store=InMemoryStateStore())
    await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    substituted = action.model_copy(update={"mode": Mode.ENFORCE})

    with pytest.raises(KineticSafetyArtifactConflictError, match="stored Action"):
        await adapter.resolve(substituted)


async def test_durable_record_omits_raw_action_arguments() -> None:
    action, plan, action_type, release = _inputs()
    state_store = InMemoryStateStore()
    adapter = StateStoreExecutedActionArtifactStore(store=state_store)

    await adapter.store(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    raw = await state_store.read_state(f"ontology:kinetic-safety-artifact:{action.action_id}")

    assert raw is not None
    assert "action" not in raw
    assert "params" not in str(raw)


def test_receipt_content_tampering_is_rejected() -> None:
    action, plan, action_type, release = _inputs()
    receipt = KineticSafetyReceipt.seal(
        action=action,
        plan=plan,
        action_type=action_type,
        active_release=release,
    )
    payload = receipt.model_dump(mode="json")
    payload["target_revision"] = receipt.target_revision + 1

    with pytest.raises(ValidationError, match="digest does not match content"):
        KineticSafetyReceipt.model_validate(payload)
