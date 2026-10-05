"""Shared approval profile contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRefusal,
    ApprovalProfileRevision,
    approval_profile_from_audit_dict,
    approval_profile_policy_digest,
    effective_quorum_for,
    evaluate_profile_approval,
    profile_transition_quorum,
)

_AT = datetime(2026, 10, 5, tzinfo=UTC)
_OPERATOR = "00000000-0000-0000-0000-00000000000A"
_EXECUTOR = "thor-executor"


def _payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": _EXECUTOR,
        "effective_from": _AT.isoformat(),
        "operator_principal": _OPERATOR,
    }
    payload["policy_digest"] = approval_profile_policy_digest(payload)
    return payload


def _single() -> ApprovalProfileRevision:
    return ApprovalProfileRevision(
        revision_id="approval-profile-r1",
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=_EXECUTOR,
        policy_digest=str(_payload()["policy_digest"]),
        effective_from=_AT,
        operator_principal=_OPERATOR,
    )


def _multi() -> ApprovalProfileRevision:
    payload = {
        "revision_id": "approval-profile-r0",
        "approval_profile": "multi-operator",
        "executor_principal": _EXECUTOR,
        "effective_from": _AT.isoformat(),
        "operator_principal": None,
    }
    return ApprovalProfileRevision(
        revision_id="approval-profile-r0",
        approval_profile=ApprovalProfileKind.MULTI_OPERATOR,
        executor_principal=_EXECUTOR,
        policy_digest=approval_profile_policy_digest(payload),
        effective_from=_AT,
    )


def test_profile_revision_invariants_and_digest() -> None:
    profile = _single()

    assert profile.policy_digest == approval_profile_policy_digest(_payload())
    with pytest.raises(ValueError, match="MUST name one operator"):
        replace(profile, operator_principal=None)
    with pytest.raises(ValueError, match="MUST NOT be the executor"):
        replace(profile, operator_principal=_EXECUTOR.upper())
    with pytest.raises(ValueError, match="MUST NOT name an operator"):
        replace(_multi(), operator_principal=_OPERATOR)
    with pytest.raises(ValueError, match="sha256"):
        replace(profile, policy_digest="latest")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(profile, effective_from=datetime(2026, 10, 5))


def test_named_operator_satisfies_quorum_and_audit() -> None:
    decision = evaluate_profile_approval(
        _single(),
        approver=_OPERATOR.lower(),
        requester=_OPERATOR,
        original_quorum=2,
        executor_principal=_EXECUTOR,
    )

    assert decision.allowed is True
    assert decision.effective_quorum == 1
    assert decision.self_review is True
    assert decision.as_audit_dict() == {
        "allowed": True,
        "approval_profile": "single-operator-production",
        "original_quorum": 2,
        "effective_quorum": 1,
        "refusal": None,
        "operator_principal": _OPERATOR,
        "self_review": True,
    }


@pytest.mark.parametrize(
    ("approver", "requester", "refusal"),
    [
        ("", "fdai-core", ApprovalProfileRefusal.BLANK_APPROVER),
        (_OPERATOR, "", ApprovalProfileRefusal.UNKNOWN_REQUESTER),
        ("somebody-else", _OPERATOR, ApprovalProfileRefusal.UNNAMED_PRINCIPAL),
        (_EXECUTOR, "fdai-core", ApprovalProfileRefusal.APPROVER_IS_EXECUTOR),
    ],
)
def test_single_operator_refusals(
    approver: str,
    requester: str,
    refusal: ApprovalProfileRefusal,
) -> None:
    decision = evaluate_profile_approval(
        _single(),
        approver=approver,
        requester=requester,
        original_quorum=2,
        executor_principal=_EXECUTOR,
    )

    assert decision.allowed is False
    assert decision.refusal is refusal


def test_multi_operator_keeps_legacy_self_approval_and_quorum() -> None:
    allowed = evaluate_profile_approval(
        None,
        approver="approver-b",
        requester="requester-a",
        original_quorum=2,
    )
    refused = evaluate_profile_approval(
        _multi(),
        approver="Requester-A",
        requester="requester-a",
        original_quorum=2,
    )

    assert allowed.allowed is True
    assert allowed.effective_quorum == 2
    assert refused.refusal is ApprovalProfileRefusal.SELF_APPROVAL


def test_quorum_and_transition_rules() -> None:
    assert effective_quorum_for(_single(), 2) == 1
    assert effective_quorum_for(_multi(), 2) == 2
    assert profile_transition_quorum(_multi(), _single(), governance_quorum=2) == 2
    assert profile_transition_quorum(_single(), _multi(), governance_quorum=2) == 1
    with pytest.raises(ValueError, match="quorum"):
        effective_quorum_for(_single(), 0)


def test_profile_reconstructs_from_audit_dict() -> None:
    profile = _single()

    assert approval_profile_from_audit_dict(None) is None
    assert approval_profile_from_audit_dict(profile.as_audit_dict()) == profile
    with pytest.raises(ValueError, match="malformed"):
        approval_profile_from_audit_dict({"approval_profile": "single-operator-production"})
