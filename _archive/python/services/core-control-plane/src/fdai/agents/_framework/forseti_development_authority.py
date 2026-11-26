"""Trusted development-authority admission owned by Forseti judgment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.development_authority import (
    admit_development_authority,
    development_binding_verification,
    development_grant,
)
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileRevision,
    effective_quorum_for,
)
from fdai.shared.contracts.models import (
    Autonomy,
    FullAuthorityDevelopmentProfile,
    RegisteredDevelopmentAction,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource


class ForsetiDevelopmentAuthorityMixin:
    """Attach only source-verified development authority to a real Verdict."""

    _development_profile: FullAuthorityDevelopmentProfile | None
    _development_binding_source: DevelopmentAuthorityBindingSource | None
    _development_executor_principal: str | None
    _development_action_types: Mapping[str, RegisteredDevelopmentAction]
    _development_clock: Callable[[], datetime]
    _approval_profile: ApprovalProfileRevision | None
    record_behavior: Callable[..., None]

    def initialize_development_authority(
        self,
        *,
        profile: FullAuthorityDevelopmentProfile | None,
        binding_source: DevelopmentAuthorityBindingSource | None,
        executor_principal: str | None,
        action_types: Mapping[str, RegisteredDevelopmentAction] | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._development_profile = profile
        self._development_binding_source = binding_source
        self._development_executor_principal = executor_principal
        self._development_action_types = dict(action_types or {})
        self._development_clock = clock or (lambda: datetime.now(tz=UTC))
        self._approval_profile = None

    def initialize_approval_profile(
        self,
        *,
        profile: ApprovalProfileRevision | None,
    ) -> None:
        self._approval_profile = profile

    def attach_approval_profile(self, verdict: dict[str, Any]) -> None:
        profile = self._approval_profile
        if profile is None:
            return
        original_quorum = int(
            verdict.get("original_quorum_required", verdict.get("quorum_required", 1))
        )
        effective_quorum = effective_quorum_for(profile, original_quorum)
        verdict["approval_profile"] = profile.as_audit_dict()
        verdict["operator_principal"] = profile.operator_principal
        verdict["original_quorum_required"] = original_quorum
        verdict["effective_quorum_required"] = effective_quorum
        verdict["quorum_required"] = effective_quorum
        self.record_behavior("approval_profile:attached")

    def attach_development_authority(
        self,
        event: Mapping[str, Any],
        verdict: dict[str, Any],
    ) -> None:
        confirmation = event.get("development_authority_confirmation")
        if self._development_profile is None and confirmation is None:
            return
        evidence = {
            "schema_version": "1.0.0",
            "confirmation": confirmation,
        }
        action_type = str(verdict.get("action_type") or "")
        original_quorum = int(verdict.get("quorum_required", 1))
        try:
            admitted = admit_development_authority(
                profile=self._development_profile,
                binding_source=self._development_binding_source,
                evidence=evidence,
                action=verdict,
                executor_principal=self._development_executor_principal,
                original_quorum=original_quorum,
                now=self._development_clock(),
            )
            grant = development_grant(admitted)
            verification = development_binding_verification(admitted)
            current = self._development_action_types.get(action_type)
            if (
                admitted is None
                or grant is None
                or verification is None
                or current is None
                or (
                    verification.binding.action_type,
                    verification.binding.action_type_version,
                    verification.binding.action_type_digest,
                )
                != (current.action_type, current.version, current.action_type_digest)
            ):
                raise ValueError("development ActionType does not match current catalog")
        except (TypeError, ValueError):
            verdict["risk_verdict"] = "deny"
            verdict["resolved_autonomy_ceiling"] = Autonomy.SHADOW_ONLY.value
            verdict["reason"] = "development_authority_invalid"
            verdict["original_quorum_required"] = original_quorum
            verdict["effective_quorum_required"] = original_quorum
            self.record_behavior("development_authority:rejected")
            return
        verdict["development_authority"] = admitted
        verdict["original_quorum_required"] = original_quorum
        verdict["effective_quorum_required"] = grant.effective_quorum
        verdict["quorum_required"] = grant.effective_quorum
        if verdict.get("risk_verdict") == "auto":
            verdict["risk_verdict"] = "hil"
            verdict["resolved_autonomy_ceiling"] = Autonomy.ENFORCE_HIL.value
        self.record_behavior("development_authority:admitted")


__all__ = ["ForsetiDevelopmentAuthorityMixin"]
