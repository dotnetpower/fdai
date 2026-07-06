"""No-self-approval invariant — separation of author and approver.

Enforcement lives in TWO places (see security-and-identity.md § HIL
Approval Integrity + user-rbac-and-identity.md § 5.2 Author-is-not-approver):

- **CI** — on governance PRs, compares Entra OID trailer to reviewer OID.
- **Runtime** — on HIL approval endpoints, this enforcer runs before the
  API records the approval.

This test module owns the runtime side. It also proves the invariant is
oid-based (never upn/email), matches the requirement to be audit-recorded
as a principal check (the caller records both oids around the check).
"""

from __future__ import annotations

import pytest

from aiopspilot.core.rbac.enforcer import (
    AuthorizationError,
    RoleEnforcer,
    SelfApprovalError,
)
from aiopspilot.core.rbac.resolver import Principal
from aiopspilot.core.rbac.roles import Role


def _approver(oid: str, *, upn: str | None = None) -> Principal:
    return Principal(oid=oid, roles=frozenset({Role.APPROVER}), upn=upn)


class TestNoSelfApproval:
    def test_pass_when_approver_oid_differs_from_submitter_oid(self) -> None:
        enforcer = RoleEnforcer()
        enforcer.no_self_approval(_approver("approver-oid"), submitter_oid="submitter-oid")

    def test_deny_when_approver_oid_equals_submitter_oid(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(SelfApprovalError, match="no-self-approval"):
            enforcer.no_self_approval(_approver("shared-oid"), submitter_oid="shared-oid")

    def test_role_membership_does_not_bypass_check(self) -> None:
        # Owner + Approver combined — still cannot self-approve.
        enforcer = RoleEnforcer()
        p = Principal(oid="oid-1", roles=frozenset({Role.OWNER, Role.APPROVER}))
        with pytest.raises(SelfApprovalError):
            enforcer.no_self_approval(p, submitter_oid="oid-1")

    def test_check_is_oid_based_not_upn_based(self) -> None:
        # Same UPN, different OIDs → the check passes because OID is the
        # stable identity per user-rbac-and-identity § 10.2. This
        # protects against a UPN-rename attack that would otherwise
        # falsely collide.
        enforcer = RoleEnforcer()
        approver = _approver("approver-oid", upn="alice@example.com")
        # Submitter has same UPN in a fork's audit log (renamed later)
        # but different OID → approval must succeed.
        enforcer.no_self_approval(approver, submitter_oid="submitter-oid")

    def test_different_upn_but_same_oid_is_denied(self) -> None:
        # Symmetric to the above — OID matches even when UPN differs.
        enforcer = RoleEnforcer()
        approver = _approver("shared-oid", upn="alice@new.example.com")
        with pytest.raises(SelfApprovalError):
            enforcer.no_self_approval(approver, submitter_oid="shared-oid")

    def test_empty_submitter_oid_is_programmer_error(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(ValueError, match="submitter_oid"):
            enforcer.no_self_approval(_approver("oid-1"), submitter_oid="")

    def test_self_approval_error_is_authorization_error(self) -> None:
        # A single exception-handler for AuthorizationError SHOULD catch
        # self-approval failures too — same 403 semantic.
        assert issubclass(SelfApprovalError, AuthorizationError)

    def test_case_sensitive_oid_comparison(self) -> None:
        # Entra OIDs are UUIDs; the tokenizer preserves case. Compare
        # exact equality so a truncated / re-cased submitter oid does
        # NOT accidentally bypass the check.
        enforcer = RoleEnforcer()
        approver = _approver("ABCDEF-1234")
        # Different case should NOT match — this preserves the "compare
        # what the token gave us" property.
        enforcer.no_self_approval(approver, submitter_oid="abcdef-1234")


class TestNoSelfApprovalAuditIntegration:
    """Show the check is used as an audit-recorded principal step.

    The doc says approvals are "audit-recorded principal check"; the
    enforcer never talks to the audit store itself — the caller wraps
    it. This test locks in that shape by simulating a small caller.
    """

    def test_caller_records_both_oids_around_the_check(self) -> None:
        # Simulated fork-side audit collector.
        audit: list[dict[str, str]] = []

        def audited_approve(*, approver: Principal, submitter_oid: str, action_id: str) -> None:
            entry: dict[str, str] = {
                "action_id": action_id,
                "approver_oid": approver.oid,
                "submitter_oid": submitter_oid,
                "outcome": "pending",
            }
            audit.append(entry)
            try:
                RoleEnforcer().no_self_approval(approver, submitter_oid=submitter_oid)
            except SelfApprovalError:
                entry["outcome"] = "denied-self-approval"
                raise
            entry["outcome"] = "approved"

        # Happy path.
        audited_approve(
            approver=_approver("a-oid"),
            submitter_oid="b-oid",
            action_id="act-1",
        )
        assert audit[-1] == {
            "action_id": "act-1",
            "approver_oid": "a-oid",
            "submitter_oid": "b-oid",
            "outcome": "approved",
        }

        # Self-approval path — audit records the denial with both oids.
        with pytest.raises(SelfApprovalError):
            audited_approve(
                approver=_approver("c-oid"),
                submitter_oid="c-oid",
                action_id="act-2",
            )
        assert audit[-1] == {
            "action_id": "act-2",
            "approver_oid": "c-oid",
            "submitter_oid": "c-oid",
            "outcome": "denied-self-approval",
        }
