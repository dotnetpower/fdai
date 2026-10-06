"""Single-operator production approval-profile checks for Var."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.action_semantics import quorum_for
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileRevision,
    approval_profile_from_audit_dict,
    evaluate_profile_approval,
)
from fdai.core.risk_gate.approval_profile_store import approval_profile_pin_is_authorized


class VarApprovalProfileMixin:
    """Validate profile-bearing tickets without changing Var's AgentSpec."""

    _approval_profile: ApprovalProfileRevision | None
    _approval_profile_bootstrap: ApprovalProfileRevision | None

    async def _admit_ticket_authority(
        self,
        payload: Mapping[str, Any],
        *,
        action_type: str,
        payload_quorum: int,
    ) -> tuple[int, int, int, dict[str, Any] | None, ApprovalProfileRevision | None]:
        original, effective, development = self._admit_development_ticket(  # type: ignore[attr-defined]
            payload,
            quorum=payload_quorum,
        )
        required = quorum_for(action_type, self._action_semantics)  # type: ignore[attr-defined]
        profile = await self._active_ticket_approval_profile(payload)
        if development is None and profile is None:
            quorum = max(payload_quorum, required)
            return quorum, quorum, quorum, None, None
        if profile is None and original < required:
            raise ValueError("development authority original quorum is below catalog quorum")
        if profile is not None:
            raw_original = int(payload.get("original_quorum_required", original))
            raw_effective = int(payload.get("effective_quorum_required", effective))
            original, effective = self._admit_approval_profile_ticket(
                profile,
                original_quorum=raw_original,
                effective_quorum=raw_effective,
                required_quorum=required,
            )
        return effective, original, effective, development, profile

    async def _active_ticket_approval_profile(
        self,
        payload: Mapping[str, Any],
    ) -> ApprovalProfileRevision | None:
        raw = payload.get("approval_profile")
        profile = approval_profile_from_audit_dict(raw if isinstance(raw, Mapping) else None)
        if profile is not None and not await approval_profile_pin_is_authorized(
            self._state_store,  # type: ignore[attr-defined]
            pinned=profile,
            bound=self._approval_profile,
            bootstrap=self._approval_profile_bootstrap,
        ):
            raise ValueError("approval profile is unavailable")
        return profile

    def _admit_approval_profile_ticket(
        self,
        profile: ApprovalProfileRevision,
        *,
        original_quorum: int,
        effective_quorum: int,
        required_quorum: int,
    ) -> tuple[int, int]:
        del profile
        original = max(original_quorum, required_quorum)
        if effective_quorum != 1:
            raise ValueError("approval profile effective quorum is invalid")
        return original, effective_quorum

    def _profile_approval_eligible(
        self,
        *,
        profile: ApprovalProfileRevision | None,
        approver: str,
        requester: str,
        original_quorum: int,
        correlation_id: str,
    ) -> bool:
        if profile is None:
            return False
        decision = evaluate_profile_approval(
            profile,
            approver=approver,
            requester=requester or "fdai-core",
            original_quorum=original_quorum,
        )
        if decision.allowed:
            return True
        refusal = decision.refusal.value if decision.refusal else "refused"
        self._record_blocked_attempt(  # type: ignore[attr-defined]
            f"approval_profile_{refusal}",
            correlation_id,
            approver,
        )
        raise PermissionError(
            f"principal {approver!r} is not admitted by the active approval profile"
        )


__all__ = ["VarApprovalProfileMixin"]
