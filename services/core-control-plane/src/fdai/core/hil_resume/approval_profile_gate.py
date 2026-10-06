"""Approval-profile gate for resolving a parked HIL decision.

A parked decision pins the approval profile that was active when it parked. Resolution refuses a
malformed pin, but it honors a valid pinned revision even after the runtime activates a newer
profile so an in-flight decision never changes approval rules mid-flight. The audit details expose
the reduced separation of duties of the single-operator production profile.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.policy_administration import PolicyRevisionSignatureVerifier

from fdai.core.hil_resume.delegation import DelegationDecision
from fdai.core.hil_resume.results import ResolveOutcome, ResolveResult
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileDecision,
    ApprovalProfileRevision,
    approval_profile_from_audit_dict,
)
from fdai.core.risk_gate.approval_profile_store import approval_profile_pin_is_authorized
from fdai.shared.providers.state_store import StateStore

MALFORMED = "approval_profile_malformed"
UNAVAILABLE = "approval_profile_unavailable"


async def parked_approval_profile(
    parked: Mapping[str, object],
    bound: ApprovalProfileRevision | None,
    bootstrap: ApprovalProfileRevision | None,
    store: StateStore | None,
    signature_verifier: PolicyRevisionSignatureVerifier | None = None,
) -> tuple[ApprovalProfileRevision | None, str | None]:
    """Return the parked profile, or a refusal reason when it can't be honored."""

    raw = parked.get("approval_profile")
    try:
        profile = approval_profile_from_audit_dict(raw if isinstance(raw, Mapping) else None)
    except ValueError:
        return None, MALFORMED
    if profile is not None and not await approval_profile_pin_is_authorized(
        store,
        pinned=profile,
        bound=bound,
        bootstrap=bootstrap,
        signature_verifier=signature_verifier,
    ):
        return None, UNAVAILABLE
    return profile, None


def approval_profile_audit_detail(
    decision: ApprovalProfileDecision | None,
) -> dict[str, object]:
    """Return the audit fields that show the active profile and its quorum reduction."""

    if decision is None:
        return {}
    audit = decision.as_audit_dict()
    return {
        "approval_profile": audit["approval_profile"],
        "original_quorum": audit["original_quorum"],
        "effective_quorum": audit["effective_quorum"],
        "operator_principal": audit["operator_principal"],
        "self_review": audit["self_review"],
    }


class HilApprovalProfileMixin:
    """Bind the deployment-selected profile and refuse approvals it doesn't admit."""

    _approval_profile: ApprovalProfileRevision | None
    _approval_profile_bootstrap: ApprovalProfileRevision | None
    _approval_profile_signature_verifier: PolicyRevisionSignatureVerifier | None

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> None:
        raise NotImplementedError

    def bind_approval_profile(self, profile: ApprovalProfileRevision) -> None:
        """Bind the selected production approval profile once."""
        if self._approval_profile is not None:
            if self._approval_profile.as_audit_dict() == profile.as_audit_dict():
                return
            raise RuntimeError("approval profile is already bound")
        self._approval_profile = profile

    async def _refuse_by_profile(
        self,
        delegation: DelegationDecision,
        *,
        idem: str,
        approval_id: str,
        correlation_id: str,
        approver_oid: str,
        assignee_oid: str | None,
    ) -> ResolveResult:
        """Audit and refuse an unnamed principal or the executor under the active profile."""
        reason = delegation.refusal.value if delegation.refusal is not None else "approval_refused"
        await self._audit(
            action_kind="hil.resolve.approval_profile_refused",
            idempotency_key=f"{idem}:hil_approval_profile_refused",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={
                "approver_oid": approver_oid,
                "assignee_oid": assignee_oid,
                "reason": reason,
                **approval_profile_audit_detail(delegation.approval_profile),
            },
        )
        return ResolveResult(
            outcome=ResolveOutcome.DECISION_REFUSED,
            approval_id=approval_id,
            reason=reason,
            assignee_oid=assignee_oid,
        )


__all__ = [
    "MALFORMED",
    "HilApprovalProfileMixin",
    "UNAVAILABLE",
    "approval_profile_audit_detail",
    "parked_approval_profile",
]
