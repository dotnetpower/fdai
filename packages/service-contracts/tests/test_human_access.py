"""Membership receipts and lock identity are distinct immutable contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from fdai_service_contracts.human_access import (
    HumanAccessOperation,
    HumanAccessOutcome,
    HumanAccessPlan,
    HumanAccessReceipt,
)


def plan() -> HumanAccessPlan:
    return HumanAccessPlan(
        "case:one", "subject:one", "group:one", HumanAccessOperation.GRANT, "key:one"
    )


def test_legacy_receipt_digest_keeps_exact_case_subject_group_and_operation() -> None:
    value = plan()
    canonical = json.dumps(
        {
            "case_id": "case:one",
            "subject_id": "subject:one",
            "group_id": "group:one",
            "operation": "grant",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert value.target_digest == hashlib.sha256(canonical.encode()).hexdigest()
    assert replace(value, idempotency_key="another").target_digest == value.target_digest


@pytest.mark.parametrize("operation", list(HumanAccessOperation))
@pytest.mark.parametrize("case_id", ["a", "case:one", "case:two", "a" * 256, "x-y_z.3:4"])
def test_membership_lock_serializes_different_cases_opposite_operations_and_retries(
    operation, case_id
) -> None:
    original = plan()
    other = replace(original, operation=operation, case_id=case_id, idempotency_key="key:other")
    assert original.membership_lock_key == other.membership_lock_key


def test_membership_identity_normalizes_case_without_rewriting_retained_receipt_target() -> None:
    original = plan()
    other = replace(
        original, subject_id=original.subject_id.upper(), group_id=original.group_id.upper()
    )
    assert other.membership_lock_key == original.membership_lock_key
    assert other.target_digest != original.target_digest


def test_lock_identity_keeps_subject_and_group_positions_and_distinct_targets() -> None:
    value = plan()
    changed = [
        replace(value, subject_id="subject:two"),
        replace(value, group_id="group:two"),
        replace(value, subject_id=value.group_id, group_id=value.subject_id),
    ]
    assert all(other.membership_lock_key != value.membership_lock_key for other in changed)
    assert "subject:one" not in value.membership_lock_key
    assert len(value.membership_lock_key) < 128


def test_plan_and_acknowledgement_never_expose_an_authority_switch() -> None:
    value = plan()
    receipt = HumanAccessReceipt(HumanAccessOutcome.APPLIED, "receipt:example", value.target_digest)
    assert not hasattr(value, "execution_authority")
    assert not hasattr(receipt, "effect_verified")
    with pytest.raises(FrozenInstanceError):
        value.group_id = "group:changed"


@pytest.mark.parametrize("outcome", [True, 1, "applied", None])
def test_provider_acknowledgement_requires_a_typed_outcome(outcome) -> None:
    with pytest.raises(ValueError, match="typed"):
        HumanAccessReceipt(outcome, "receipt:example", plan().target_digest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_id", "../other"),
        ("subject_id", "x/y"),
        ("group_id", "group?query"),
        ("idempotency_key", " "),
        ("subject_id", True),
    ],
)
def test_plan_rejects_unsafe_path_or_ambiguous_identifier(field, value) -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        replace(plan(), **{field: value})
