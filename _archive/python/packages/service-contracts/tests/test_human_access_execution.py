"""Exact pre-review material and independently current approval/source contract checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.executor_models import Action
from fdai_service_contracts.human_access import HumanAccessOperation, HumanAccessPlan
from fdai_service_contracts.human_access_execution import (
    HumanAccessCurrentEvidence,
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
)

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)


def material(*, elevated=False, revoke=False):
    membership = HumanAccessPlan(
        "case:example",
        "person:subject",
        "group:owner" if elevated else "group:reader",
        HumanAccessOperation.REVOKE if revoke else HumanAccessOperation.GRANT,
        "key:example",
    )
    action_type = "ops.revoke-human-access" if revoke else "ops.apply-human-access"
    action = Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000021",
            "event_id": "00000000-0000-0000-0000-000000000022",
            "idempotency_key": "key:example",
            "action_type": action_type,
            "target_resource_ref": membership.membership_lock_key.removeprefix("fdai:resource:"),
            "operation": "detach" if revoke else "attach",
            "mode": "enforce",
            "params": {
                "case_id": membership.case_id,
                "expected_revision": 5,
                **(
                    {"replacement_revisions": {"case:primary": 8, "case:backup": 8}}
                    if revoke
                    else {}
                ),
            },
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [
                {"kind": "provider_api_error_streak", "count": 3},
                {"kind": "time_box_exceeded_seconds", "seconds": 120},
            ],
            "rollback_ref": {"kind": "scripted", "reference": "recovery:membership:example"},
            "blast_radius": {"scope": "resource", "count": 1},
            "citing_rules": ["rule:assignment-reviewed"],
            "created_at": AT,
            "executor_identity_ref": "identity/human-access",
            "action_type_ref": {
                "kind": "action",
                "name": action_type,
                "version": "1.0.0",
                "catalog_digest": "sha256:" + "a" * 64,
            },
        }
    )
    return HumanAccessExecutionMaterial(
        action_json=canonical_human_access_json(action.model_dump(mode="json")),
        subject_id=membership.subject_id,
        group_id=membership.group_id,
        requested_role="Owner" if elevated else "Reader",
        requester_ref="person:requester",
        case_record_digest="b" * 64,
        role_groups_digest="c" * 64,
        promotion_record_digest="d" * 64,
        approval_ids=("approval:one", "approval:two") if elevated else ("approval:one",),
        recorded_at=AT,
        expires_at=AT + timedelta(minutes=5),
    )


def evidence(value):
    return HumanAccessCurrentEvidence.model_validate(
        {
            "material_digest": value.digest,
            "prepared_from_case_digest": value.case_record_digest,
            "prepared_from_revision": 5,
            "current_case_revision": 6,
            "current_case_state": "iam_applying",
            "preparation_ref": "preparation:example",
            "role_groups_digest": value.role_groups_digest,
            "promotion_record_digest": value.promotion_record_digest,
            "promotion_mode": "enforce",
            "current_owner_refs": [
                "person:requester",
                "person:reviewer-one",
                "person:reviewer-two",
            ],
            "observed_at": AT + timedelta(seconds=5),
            "expires_at": AT + timedelta(seconds=35),
            "approvals": [
                {
                    "approval_id": ref,
                    "approver_ref": "person:reviewer-one" if index == 0 else "person:reviewer-two",
                    "action_digest": value.action_digest,
                    "material_digest": value.digest,
                    "decision": "approve",
                    "decided_at": AT + timedelta(seconds=2),
                    "expires_at": value.expires_at,
                    "source_record_digest": "e" * 64,
                }
                for index, ref in enumerate(value.approval_ids)
            ],
        }
    )


@pytest.mark.parametrize(
    "elevated,revoke", [(False, False), (True, False), (False, True), (True, True)]
)
def test_exact_current_human_source_evidence_does_not_rewrite_action(elevated, revoke):
    value = material(elevated=elevated, revoke=revoke)
    original = value.action_json
    assert evidence(value).refusal(value, now=AT + timedelta(seconds=10)) is None
    copy = value.action()
    copy.params["expected_revision"] = 100
    assert value.action_json == original and value.action().params["expected_revision"] == 5
    assert (
        value.membership_plan().membership_lock_key
        == "fdai:resource:" + value.action().target_resource_ref
    )


@pytest.mark.parametrize(
    "field,changed",
    [
        ("executor_identity_ref", "identity/change"),
        ("target_resource_ref", "human-assignment:case:example"),
        ("operation", "delete"),
        ("params", {"case_id": "case:example", "expected_revision": True}),
        ("blast_radius", {"scope": "subscription", "count": 1}),
        ("action_type_ref", None),
    ],
)
def test_material_refuses_unreviewable_action_identity_or_coerced_source(field, changed):
    value = material()
    action = value.action().model_dump(mode="json")
    action[field] = changed
    with pytest.raises(ValueError):
        HumanAccessExecutionMaterial.model_validate(
            {**value.model_dump(), "action_json": canonical_human_access_json(action)}
        )


@pytest.mark.parametrize(
    "field,changed",
    [
        ("current_case_revision", 7),
        ("current_case_state", "degraded"),
        ("prepared_from_case_digest", "f" * 64),
        ("promotion_mode", "shadow"),
        ("role_groups_digest", "f" * 64),
        ("promotion_record_digest", "f" * 64),
        ("current_owner_refs", ("person:reviewer-one",)),
        ("approvals", ()),
    ],
)
def test_changed_current_case_role_map_promotion_or_human_evidence_holds(field, changed):
    value = material()
    current = HumanAccessCurrentEvidence.model_validate(
        {**evidence(value).model_dump(), field: changed}
    )
    assert current.refusal(value, now=AT + timedelta(seconds=10)) is not None


@pytest.mark.parametrize("actor", ["person:subject", "person:requester", "PERSON:REVIEWER-ONE"])
def test_requester_subject_and_case_changed_actor_cannot_supply_independent_review(actor):
    value = material()
    current = evidence(value).model_dump()
    current["approvals"][0]["approver_ref"] = actor
    assert (
        HumanAccessCurrentEvidence.model_validate(current).refusal(
            value, now=AT + timedelta(seconds=10)
        )
        is not None
    )


def test_two_approval_slots_require_different_current_people():
    value = material(elevated=True)
    current = evidence(value).model_dump()
    current["approvals"][1]["approver_ref"] = current["approvals"][0]["approver_ref"]
    assert (
        HumanAccessCurrentEvidence.model_validate(current).refusal(
            value, now=AT + timedelta(seconds=10)
        )
        == "human_access_current_human_separation_failed"
    )


@pytest.mark.parametrize("seconds", [4, 35, 300])
def test_source_window_and_original_review_deadline_are_half_open(seconds):
    value = material()
    assert evidence(value).refusal(value, now=AT + timedelta(seconds=seconds)) is not None


def test_same_material_with_replaced_approval_or_extended_deadline_is_held():
    value = material()
    for field, changed in [
        ("action_digest", "sha256:" + "f" * 64),
        ("material_digest", "f" * 64),
        ("decision", "reject"),
        ("expires_at", value.expires_at + timedelta(seconds=1)),
    ]:
        current = evidence(value).model_dump()
        current["approvals"][0][field] = changed
        assert (
            HumanAccessCurrentEvidence.model_validate(current).refusal(
                value, now=AT + timedelta(seconds=10)
            )
            is not None
        )
