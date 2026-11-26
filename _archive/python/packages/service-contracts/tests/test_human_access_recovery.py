"""Fresh inverse material, exact owned mutation and legacy-byte regression properties."""

from datetime import timedelta
from pathlib import Path
from runpy import run_path
from uuid import UUID

import pytest
from fdai_service_contracts.executor_models import Action
from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
)
from fdai_service_contracts.human_access_recovery import (
    HumanAccessInverseBinding,
    mutation_evidence_digest,
    require_inverse_fence,
)

_fixture = run_path(str(Path(__file__).with_name("test_human_access_execution.py")))


def inverse_material(*, revoke=False):
    original = _fixture["material"](revoke=revoke)
    action = original.action()
    identity = {
        "action_digest": original.action_digest,
        "material_digest": original.digest,
        "target_digest": original.membership_plan().target_digest,
        "idempotency_key": action.idempotency_key,
    }
    intent = {
        **identity,
        "before_membership": revoke,
        "recorded_at": original.recorded_at.isoformat(),
    }
    completed = original.recorded_at + timedelta(seconds=10)
    result = {
        **identity,
        "outcome": "succeeded",
        "receipt_ref": "dispatch:original",
        "owned_mutation": True,
        "recorded_at": completed.isoformat(),
    }
    inverse = HumanAccessInverseBinding(
        original_action_id=action.action_id,
        original_action_digest=original.action_digest,
        original_material_digest=original.digest,
        original_idempotency_key=action.idempotency_key,
        original_target_digest=identity["target_digest"],
        original_attempt_digest=mutation_evidence_digest(intent, result),
        original_before_membership=revoke,
        original_receipt_ref="dispatch:original",
        original_completed_at=completed,
        target_fence_digest="sha256:" + "f" * 64,
        target_fence_generation=1,
        demand_digest="e" * 64,
    )
    payload = action.model_dump(mode="json")
    payload.update(
        action_id=str(UUID(int=30)),
        event_id=str(UUID(int=31)),
        idempotency_key="inverse:original",
        action_type="ops.apply-human-access" if revoke else "ops.revoke-human-access",
        operation="attach" if revoke else "detach",
        created_at=(completed + timedelta(seconds=1)).isoformat(),
        params={
            "case_id": action.params["case_id"],
            "expected_revision": 7,
            "recovery_of": str(action.action_id),
        },
    )
    payload["action_type_ref"]["name"] = payload["action_type"]
    candidate = HumanAccessExecutionMaterial.model_validate(
        {
            **original.model_dump(mode="json"),
            "action_json": canonical_human_access_json(
                Action.model_validate(payload).model_dump(mode="json")
            ),
            "inverse": inverse,
            "approval_ids": ["approval:fresh"],
            "recorded_at": completed + timedelta(seconds=1),
            "expires_at": completed + timedelta(minutes=5),
        }
    )
    return original, candidate, intent, result


@pytest.mark.parametrize("revoke", [False, True])
def test_inverse_pins_original_owned_prestate_and_same_membership_lock(revoke):
    original, inverse, intent, result = inverse_material(revoke=revoke)
    inverse.inverse.require_owned(intent, result)
    assert (
        inverse.membership_plan().membership_lock_key
        == original.membership_plan().membership_lock_key
    )
    assert (
        inverse.membership_plan().desired_membership
        is not original.membership_plan().desired_membership
    )
    assert set(inverse.approval_ids).isdisjoint(original.approval_ids)
    assert inverse.action_digest != original.action_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("owned_mutation", False),
        ("owned_mutation", 1),
        ("outcome", "already_applied"),
        ("material_digest", "a" * 64),
        ("receipt_ref", "other:receipt"),
        ("recorded_at", "2026-09-15T12:01:00+00:00"),
    ],
)
def test_unowned_or_substituted_acknowledgement_cannot_be_inverted(field, value):
    _, inverse, intent, result = inverse_material()
    result[field] = value
    with pytest.raises(ValueError, match="owned mutation"):
        inverse.inverse.require_owned(intent, result)


def test_numeric_prestate_is_not_boolean_ownership_evidence():
    _, inverse, intent, result = inverse_material()
    intent["before_membership"] = 0
    with pytest.raises(ValueError):
        inverse.inverse.require_owned(intent, result)


def test_forward_material_serialization_omits_absent_inverse_and_roundtrips():
    original = _fixture["material"]()
    assert "inverse" not in original.model_dump(mode="json")
    assert (
        HumanAccessExecutionMaterial.model_validate_json(original.model_dump_json()).digest
        == original.digest
    )


def test_original_action_cannot_be_relabelled_as_its_inverse():
    original, inverse, _, _ = inverse_material()
    with pytest.raises(ValueError):
        HumanAccessExecutionMaterial.model_validate(
            {**inverse.model_dump(), "action_json": original.action_json}
        )


@pytest.mark.parametrize(
    "generation,key,state",
    [
        (3, "inverse:original", "quarantined"),
        (2, "other:attempt", "quarantined"),
        (1, "key:example", "in_flight"),
    ],
)
def test_intervening_target_generation_or_other_attempt_cannot_supply_inverse_lineage(
    generation, key, state
):
    _, inverse, _, _ = inverse_material()
    with pytest.raises(ValueError, match="intervening"):
        require_inverse_fence(
            inverse.inverse,
            {
                "state": state,
                "record_digest": "sha256:" + "f" * 64,
                "identity": {"generation": generation, "sink_idempotency_key": key},
            },
            inverse_key="inverse:original",
        )
