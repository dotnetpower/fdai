"""Tests for the HIL delegation gate.

Locks the fail-closed order and the delegation modes that back Scenario A
(operator A approves a HIL item surfaced to operator B, same authority).
"""

from __future__ import annotations

import pytest
from fdai.core.hil_resume.delegation import (
    DelegationMode,
    DelegationRefusal,
    evaluate_hil_delegation,
)


def _eval(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        approver_oid="user-a",
        submitter_oid="system",
        approver_can_approve_hil=True,
        assignee_oid=None,
    )
    base.update(kw)
    return evaluate_hil_delegation(**base)  # type: ignore[arg-type]


class TestRefusals:
    def test_blank_approver(self) -> None:
        d = _eval(approver_oid="  ")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.BLANK_APPROVER

    def test_unknown_submitter(self) -> None:
        d = _eval(submitter_oid="")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.UNKNOWN_SUBMITTER

    def test_self_approval(self) -> None:
        d = _eval(approver_oid="user-a", submitter_oid="user-a")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.SELF_APPROVAL

    def test_missing_capability(self) -> None:
        d = _eval(approver_can_approve_hil=False)
        assert not d.allowed
        assert d.refusal is DelegationRefusal.MISSING_CAPABILITY

    def test_self_approval_precedes_capability(self) -> None:
        # A self-approver without the capability is refused for self-approval
        # (the harder invariant), not the softer rbac reason.
        d = _eval(approver_oid="x", submitter_oid="x", approver_can_approve_hil=False)
        assert d.refusal is DelegationRefusal.SELF_APPROVAL


class TestAllowed:
    def test_role_scoped_when_no_assignee(self) -> None:
        d = _eval(assignee_oid=None)
        assert d.allowed
        assert d.mode is DelegationMode.ROLE_SCOPED
        assert d.refusal is None
        assert not d.is_delegated

    def test_direct_when_approver_is_assignee(self) -> None:
        d = _eval(approver_oid="user-b", assignee_oid="user-b")
        assert d.allowed
        assert d.mode is DelegationMode.DIRECT
        assert not d.is_delegated

    def test_delegated_when_approver_differs_from_assignee(self) -> None:
        # Scenario A: HIL surfaced to user-b, approved by user-a (same authority).
        d = _eval(approver_oid="user-a", submitter_oid="system", assignee_oid="user-b")
        assert d.allowed
        assert d.mode is DelegationMode.DELEGATED
        assert d.is_delegated

    def test_delegation_still_refuses_self_approval(self) -> None:
        # Even with an assignee, the approver may never be the submitter.
        d = _eval(approver_oid="user-a", submitter_oid="user-a", assignee_oid="user-b")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.SELF_APPROVAL

    def test_whitespace_is_trimmed(self) -> None:
        d = _eval(approver_oid=" user-a ", assignee_oid=" user-a ")
        assert d.allowed
        assert d.mode is DelegationMode.DIRECT


_OID = "00000000-0000-0000-0000-0000000000ab"
_OTHER = "00000000-0000-0000-0000-0000000000cd"


def _alternating_case(value: str) -> str:
    return "".join(c.upper() if index % 2 else c for index, c in enumerate(value))


@pytest.mark.parametrize(
    "recase",
    [str.upper, _alternating_case, lambda value: f"  {value.upper()}  "],
    ids=["upper", "alternating", "upper-with-padding"],
)
def test_recasing_an_object_id_is_not_a_second_person(recase: object) -> None:
    """An Entra object id is a GUID, and a GUID is the same value however it is
    cased. Comparing raw strings let one person appear as two and approve their
    own submission - the exact thing this floor exists to prevent.
    """
    decision = evaluate_hil_delegation(
        approver_oid=recase(_OID),  # type: ignore[operator]
        submitter_oid=_OID,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is False
    assert decision.refusal is DelegationRefusal.SELF_APPROVAL


def test_a_recased_assignee_is_still_a_direct_approval() -> None:
    """Casing must not turn the assignee into someone else either; that would
    record a direct approval as a delegation and misstate the audit.
    """
    decision = evaluate_hil_delegation(
        approver_oid=_OTHER.upper(),
        submitter_oid=_OID,
        assignee_oid=_OTHER,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is True
    assert decision.mode is DelegationMode.DIRECT


def test_two_genuinely_different_operators_are_still_allowed() -> None:
    decision = evaluate_hil_delegation(
        approver_oid=_OTHER,
        submitter_oid=_OID,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is True
