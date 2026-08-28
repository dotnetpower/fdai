"""Deterministic Cost Governance decision coordination over typed evidence.

The coordinator validates bounded recovery evidence and emits a decision record.
It never calls an agent, approves, executes, audits, or performs rollback.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.cost_governance_decision import (
    COST_RECOVERY_ORDER,
    CostAutonomyCeiling,
    CostCoordinationRequest,
    CostDecisionFrame,
    CostDecisionOutcome,
    CostDecisionRecord,
    CostRecoveryAttempt,
    CostRecoveryAttemptStatus,
    CostRecoveryStep,
)


class CostCoordinationError(ValueError):
    """A recovery trace violated order, scope, release, or ceiling invariants."""


@dataclass(slots=True)
class CostObservationModeLatch:
    """Sticky process-local hard-dependency safety latch.

    A failed Saga or Vidar health observation lowers subsequent decisions to
    observation mode until composition creates a new runtime instance.
    """

    _sticky: bool = False

    def observe(self, *, saga_available: bool, vidar_available: bool) -> bool:
        self._sticky = self._sticky or not saga_available or not vidar_available
        return self._sticky

    @property
    def observation_mode(self) -> bool:
        return self._sticky


class DeterministicCostCoordinator:
    """Validate the fixed recovery order and emit one authority-neutral result."""

    def __init__(self, *, latch: CostObservationModeLatch | None = None) -> None:
        self._latch = latch or CostObservationModeLatch()

    def coordinate(self, request: CostCoordinationRequest) -> CostDecisionRecord:
        """Evaluate a bounded trace without performing its requested effect."""

        frame, ceiling, evidence = self._validate_attempts(request)
        observation_mode = self._latch.observe(
            saga_available=request.dependencies.saga_available,
            vidar_available=request.dependencies.vidar_available,
        )
        evidence.update(frame.evidence_refs)

        if observation_mode:
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.HOLD,
                "hard_dependency_observation_mode",
                terminal=False,
                observation_mode=True,
                evidence=evidence,
            )
        if not request.dependencies.forseti_available:
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.HOLD,
                "forseti_judgment_unavailable",
                terminal=False,
                observation_mode=False,
                evidence=evidence,
            )
        if frame.policy_denied:
            return self._audited_terminal(
                frame,
                request,
                CostDecisionOutcome.DENY,
                "policy_denied",
                evidence,
            )
        if frame.rollback_required:
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.ROLLBACK,
                "rollback_requested",
                terminal=False,
                observation_mode=False,
                evidence=evidence,
            )

        selected = frame.selected_option
        if selected is None:
            return self._hold_or_approval(
                frame,
                request,
                ceiling=ceiling,
                evidence=evidence,
                reason="safe_option_unresolved",
            )
        if not selected.safe:
            return self._hold_or_approval(
                frame,
                request,
                ceiling=ceiling,
                evidence=evidence,
                reason="selected_option_unsafe",
            )
        if selected.no_action:
            return self._audited_terminal(
                frame,
                request,
                CostDecisionOutcome.NO_OP,
                "safe_no_action_selected",
                evidence,
            )
        if not self._step_succeeded(request.attempts, CostRecoveryStep.SELECT_SAFE_OPTION):
            return self._hold_or_approval(
                frame,
                request,
                ceiling=ceiling,
                evidence=evidence,
                reason="safe_option_not_confirmed",
            )

        requires_approval = (
            selected.policy_requires_approval
            or selected.irreversible
            or frame.residual_risk
            or ceiling < CostAutonomyCeiling.EXECUTION_ELIGIBLE
        )
        if requires_approval:
            if request.approval_granted is None:
                reason = (
                    "var_unavailable"
                    if not request.dependencies.var_available
                    else "approval_pending"
                )
                return self._decision(
                    frame,
                    request,
                    CostDecisionOutcome.APPROVAL,
                    reason,
                    terminal=False,
                    observation_mode=False,
                    evidence=evidence,
                )
            if request.approval_granted is False:
                return self._audited_terminal(
                    frame,
                    request,
                    CostDecisionOutcome.DENY,
                    "approval_denied",
                    evidence,
                )
            if not request.dependencies.var_available:
                raise CostCoordinationError("approval receipt requires available Var")
            evidence.add(request.approval_receipt_digest or "")

        if request.saga_intent_audit_digest is None:
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.HOLD,
                "saga_intent_audit_required",
                terminal=False,
                observation_mode=False,
                evidence=evidence,
            )
        evidence.add(request.saga_intent_audit_digest)
        return self._decision(
            frame,
            request,
            CostDecisionOutcome.EXECUTE,
            "eligible_effect_request",
            terminal=False,
            observation_mode=False,
            evidence=evidence,
        )

    def _validate_attempts(
        self,
        request: CostCoordinationRequest,
    ) -> tuple[CostDecisionFrame, CostAutonomyCeiling, set[str]]:
        frame = request.frame
        ceiling = request.initial_ceiling
        evidence = set(frame.evidence_refs)
        hypotheses: set[str] = set()
        seen_steps: set[CostRecoveryStep] = set()
        expected_index = 0
        previous_attempted_at = request.frame.evidence_cutoff
        for attempt in request.attempts:
            if expected_index >= len(COST_RECOVERY_ORDER):
                raise CostCoordinationError("recovery trace exceeds the fixed order")
            if attempt.step is not COST_RECOVERY_ORDER[expected_index]:
                raise CostCoordinationError("recovery trace MUST follow the fixed bounded order")
            if attempt.step in seen_steps:
                raise CostCoordinationError("recovery step MUST NOT be retried")
            if attempt.hypothesis_id in hypotheses:
                raise CostCoordinationError("recovery attempt MUST use a new hypothesis")
            if attempt.input_frame_digest != frame.digest:
                raise CostCoordinationError("recovery attempt input frame does not match")
            if attempt.autonomy_ceiling > ceiling:
                raise CostCoordinationError("recovery attempt MUST NOT raise autonomy")
            if attempt.attempted_at < previous_attempted_at:
                raise CostCoordinationError("recovery attempts MUST preserve event-time order")
            if attempt.attempted_at > request.hold_deadline:
                raise CostCoordinationError("recovery attempt exceeded the bounded hold deadline")
            hypotheses.add(attempt.hypothesis_id)
            seen_steps.add(attempt.step)
            previous_attempted_at = attempt.attempted_at
            evidence.update(attempt.evidence_refs)
            ceiling = attempt.autonomy_ceiling
            if attempt.status is CostRecoveryAttemptStatus.SUCCESS:
                output = attempt.output_frame
                if output is None:
                    raise AssertionError("successful attempt output validated by contract")
                self._validate_frame_transition(frame, output, attempt)
                frame = output
            expected_index += 1
        return frame, ceiling, evidence

    def _validate_frame_transition(
        self,
        previous: CostDecisionFrame,
        candidate: CostDecisionFrame,
        attempt: CostRecoveryAttempt,
    ) -> None:
        if (
            candidate.episode_id != previous.episode_id
            or candidate.package_id != previous.package_id
            or candidate.ontology_release_digest != previous.ontology_release_digest
            or candidate.semantic_profile_digest != previous.semantic_profile_digest
        ):
            raise CostCoordinationError("recovery MUST preserve exact package and release identity")
        if candidate.evidence_cutoff < previous.evidence_cutoff:
            raise CostCoordinationError("recovery MUST NOT move the evidence cutoff backward")
        if not candidate.scope.does_not_widen(previous.scope):
            raise CostCoordinationError("recovery MUST NOT widen target or impact scope")
        previous_options = {option.option_id: option for option in previous.options}
        candidate_options = {option.option_id: option for option in candidate.options}
        if not set(candidate_options) <= set(previous_options):
            raise CostCoordinationError("recovery MUST NOT introduce a new option")
        for option_id, option in candidate_options.items():
            prior = previous_options[option_id]
            if (
                option.action_type_id != prior.action_type_id
                or option.unsafe_reasons != prior.unsafe_reasons
                or option.reversible != prior.reversible
                or option.safeguards_complete != prior.safeguards_complete
                or option.no_action != prior.no_action
                or option.policy_requires_approval != prior.policy_requires_approval
                or option.irreversible != prior.irreversible
                or not option.scope.does_not_widen(prior.scope)
            ):
                raise CostCoordinationError(
                    "recovery MUST preserve option safety and only reduce its scope"
                )
        if attempt.step is CostRecoveryStep.REACQUIRE_CONTEXT and (
            candidate.evidence_cutoff <= previous.evidence_cutoff
        ):
            raise CostCoordinationError("context reacquisition MUST use a fresh cutoff")
        if attempt.step is CostRecoveryStep.INDEPENDENT_SOURCE and (
            set(candidate.evidence_refs) <= set(previous.evidence_refs)
            or attempt.independent_source_authority is None
        ):
            raise CostCoordinationError("independent-source recovery MUST add evidence")
        if attempt.step is CostRecoveryStep.REMOVE_UNSAFE_OPTIONS and (
            any(option.unsafe_reasons for option in candidate.options)
            or any(
                option_id in candidate_options
                for option_id, option in previous_options.items()
                if option.unsafe_reasons
            )
        ):
            raise CostCoordinationError("unsafe-option recovery MUST remove unsafe options")
        if attempt.step is CostRecoveryStep.REDUCE_SCOPE and (candidate.scope == previous.scope):
            raise CostCoordinationError("scope reduction MUST reduce at least one dimension")
        if attempt.step is CostRecoveryStep.SELECT_SAFE_OPTION and (
            candidate.selected_option is None or not candidate.selected_option.safe
        ):
            raise CostCoordinationError("safe-option selection MUST select a safe option")

    def _hold_or_approval(
        self,
        frame: CostDecisionFrame,
        request: CostCoordinationRequest,
        *,
        ceiling: CostAutonomyCeiling,
        evidence: set[str],
        reason: str,
    ) -> CostDecisionRecord:
        hold_attempted = any(
            attempt.step is CostRecoveryStep.BOUNDED_HOLD for attempt in request.attempts
        )
        approval_attempted = any(
            attempt.step is CostRecoveryStep.RESIDUAL_APPROVAL for attempt in request.attempts
        )
        if (
            hold_attempted
            and not approval_attempted
            and frame.evidence_cutoff < request.hold_deadline
        ):
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.HOLD,
                reason,
                terminal=False,
                observation_mode=False,
                evidence=evidence,
            )
        if approval_attempted or ceiling <= CostAutonomyCeiling.APPROVAL:
            return self._decision(
                frame,
                request,
                CostDecisionOutcome.APPROVAL,
                "residual_approval_required",
                terminal=False,
                observation_mode=False,
                evidence=evidence,
            )
        return self._decision(
            frame,
            request,
            CostDecisionOutcome.HOLD,
            reason,
            terminal=False,
            observation_mode=False,
            evidence=evidence,
        )

    def _audited_terminal(
        self,
        frame: CostDecisionFrame,
        request: CostCoordinationRequest,
        outcome: CostDecisionOutcome,
        reason: str,
        evidence: set[str],
    ) -> CostDecisionRecord:
        terminal = request.terminal_audit_digest is not None
        if request.terminal_audit_digest is not None:
            evidence.add(request.terminal_audit_digest)
        return self._decision(
            frame,
            request,
            outcome,
            reason if terminal else "terminal_audit_required",
            terminal=terminal,
            observation_mode=False,
            evidence=evidence,
        )

    @staticmethod
    def _step_succeeded(
        attempts: tuple[CostRecoveryAttempt, ...],
        step: CostRecoveryStep,
    ) -> bool:
        return any(
            attempt.step is step and attempt.status is CostRecoveryAttemptStatus.SUCCESS
            for attempt in attempts
        )

    @staticmethod
    def _decision(
        frame: CostDecisionFrame,
        request: CostCoordinationRequest,
        outcome: CostDecisionOutcome,
        reason: str,
        *,
        terminal: bool,
        observation_mode: bool,
        evidence: set[str],
    ) -> CostDecisionRecord:
        evidence.discard("")
        return CostDecisionRecord(
            episode_id=frame.episode_id,
            outcome=outcome,
            reason=reason,
            decision_frame_digest=frame.digest,
            terminal=terminal,
            observation_mode=observation_mode,
            selected_option_id=frame.selected_option_id,
            hold_deadline=request.hold_deadline if outcome is CostDecisionOutcome.HOLD else None,
            evidence_refs=tuple(sorted(evidence)),
        )


__all__ = [
    "CostCoordinationError",
    "CostObservationModeLatch",
    "DeterministicCostCoordinator",
]
