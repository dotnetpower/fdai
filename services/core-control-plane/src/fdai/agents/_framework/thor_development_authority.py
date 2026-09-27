"""Full-authority development checks kept behind Thor's existing role."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.agents._framework import thor_execution
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.development_authority import (
    admit_development_authority,
    development_grant,
)
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import (
    DevelopmentAuthorityGrant,
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource


@dataclass(frozen=True, slots=True)
class DevelopmentVerdictAuthority:
    risk_verdict: str
    effective_quorum: int
    evidence: dict[str, Any] | None
    grant: DevelopmentAuthorityGrant | None


class ThorDevelopmentAuthorityMixin:
    """Revalidate development authority without changing Thor's AgentSpec."""

    _development_profile: FullAuthorityDevelopmentProfile | None
    _development_executor_principal: str | None
    _development_binding_source: DevelopmentAuthorityBindingSource | None
    _require_execution_audit: bool
    _require_execution_resource_lock: bool
    _now: Callable[[], datetime]
    record_behavior: Callable[..., None]
    _emit_action_run: Callable[[ActionRun], Awaitable[None]]
    _release_resource_claim: Callable[[ActionRun], Awaitable[None]]
    _release_lock: Callable[[Any], None]

    def _initialize_development_authority(
        self,
        profile: FullAuthorityDevelopmentProfile | None,
        executor_principal: str | None,
        binding_source: DevelopmentAuthorityBindingSource | None,
    ) -> None:
        self._development_profile = profile
        self._development_executor_principal = executor_principal
        self._development_binding_source = binding_source
        if profile is not None:
            self._require_execution_audit = True
            self._require_execution_resource_lock = True

    def set_development_authority(
        self,
        profile: FullAuthorityDevelopmentProfile | None,
        *,
        executor_principal: str | None,
        binding_source: DevelopmentAuthorityBindingSource | None,
    ) -> None:
        """Bind the explicitly selected profile and observed executor identity."""

        self._initialize_development_authority(
            profile,
            executor_principal,
            binding_source,
        )

    def _admit_development_verdict(
        self,
        *,
        evidence: object,
        action: Mapping[str, Any],
        risk_verdict: str,
        original_quorum: int,
        effective_quorum: int,
    ) -> DevelopmentVerdictAuthority:
        try:
            admitted = admit_development_authority(
                profile=self._development_profile,
                binding_source=self._development_binding_source,
                evidence=evidence,
                action=action,
                executor_principal=self._development_executor_principal,
                original_quorum=original_quorum,
                now=self._now(),
            )
        except ValueError:
            self.record_behavior("development_authority:rejected")
            return DevelopmentVerdictAuthority("deny", effective_quorum, None, None)
        if admitted is None:
            return DevelopmentVerdictAuthority(
                risk_verdict,
                effective_quorum,
                None,
                None,
            )
        grant = development_grant(admitted)
        if grant is None:
            self.record_behavior("development_authority:rejected")
            return DevelopmentVerdictAuthority("deny", effective_quorum, None, None)
        self.record_behavior("development_authority:admitted")
        return DevelopmentVerdictAuthority(
            "hil" if risk_verdict == "auto" else risk_verdict,
            grant.effective_quorum,
            admitted,
            grant,
        )

    def _validate_development_approval(
        self,
        run: ActionRun,
        approval: Mapping[str, Any],
    ) -> None:
        if run.development_authority is None:
            return
        try:
            admitted = self._admit_current_development_authority(run)
        except ValueError as exc:
            self.record_behavior("approval:development_authority_stale")
            raise ValueError("development authority is no longer current") from exc
        grant = development_grant(admitted)
        approvers = approval.get("approvers")
        if (
            grant is None
            or approval.get("development_authority") != run.development_authority
            or approval.get("original_quorum_required") != run.original_quorum_required
            or approval.get("effective_quorum_required") != run.effective_quorum_required
            or not isinstance(approvers, list)
            or approvers != [normalized_principal(grant.owner_principal)]
        ):
            self.record_behavior("approval:development_authority_mismatch")
            raise ValueError("approval does not preserve exact development authority")

    def _admit_current_development_authority(
        self,
        run: ActionRun,
    ) -> dict[str, Any] | None:
        return admit_development_authority(
            profile=self._development_profile,
            binding_source=self._development_binding_source,
            evidence=run.development_authority,
            action=run.to_dict(),
            executor_principal=self._development_executor_principal,
            original_quorum=run.original_quorum_required or run.quorum_required,
            now=self._now(),
        )

    def _revalidate_development_authority(self, run: ActionRun) -> None:
        self._admit_current_development_authority(run)

    async def _execute(self, run: ActionRun) -> None:
        try:
            self._revalidate_development_authority(run)
        except ValueError:
            run.transition(ActionRunState.DENY_DROPPED)
            run.outcome = "development_authority_revalidation_failed"
            await self._emit_action_run(run)
            await self._release_resource_claim(run)
            self._release_lock(run.resource_id)
            self.record_behavior("development_authority:revalidation_failed")
            return
        await thor_execution.execute(self, run)  # type: ignore[arg-type]


__all__ = ["DevelopmentVerdictAuthority", "ThorDevelopmentAuthorityMixin"]
