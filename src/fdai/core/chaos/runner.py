"""End-to-end governed chaos enforcement runner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult, FaultScenario
from fdai.core.chaos.governance import (
    ChaosEligibilityContext,
    ChaosEligibilityDecision,
    evaluate_chaos_eligibility,
)
from fdai.core.chaos.guard import ImpactGuard
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.run_store import ChaosRunStore
from fdai.core.recovery import (
    PreauthorizedRecoveryController,
    RecoveryControlResult,
    RecoveryEvidenceCollector,
    RecoveryPlanRecord,
    RecoveryVerification,
    RecoveryVerificationOutcome,
    verify_recovery_postconditions,
)
from fdai.shared.contracts.models import Mode


@dataclass(frozen=True, slots=True)
class GovernedChaosRunResult:
    run_id: str
    eligibility: ChaosEligibilityDecision
    state: ChaosRunSnapshot
    experiment: ExperimentResult | None
    recovery: RecoveryControlResult | None
    verification: RecoveryVerification | None


class GovernedChaosRunner:
    def __init__(
        self,
        *,
        harness: FaultInjectionHarness,
        run_store: ChaosRunStore,
        recovery: PreauthorizedRecoveryController,
        evidence_collector: RecoveryEvidenceCollector,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._harness = harness
        self._run_store = run_store
        self._recovery = recovery
        self._evidence_collector = evidence_collector
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def run_enforce(
        self,
        *,
        run_id: str,
        scenario: FaultScenario,
        eligibility_context: ChaosEligibilityContext,
        recovery_plan: RecoveryPlanRecord,
        impact_guard: ImpactGuard,
        guard_interval_seconds: float = 5.0,
    ) -> GovernedChaosRunResult:
        state = await self._run_store.create(run_id=run_id, at=self._now())
        decision = evaluate_chaos_eligibility(eligibility_context)
        if state.state.terminal:
            return GovernedChaosRunResult(run_id, decision, state, None, None, None)
        if state.state in {
            ChaosRunState.INJECTING,
            ChaosRunState.OBSERVING,
            ChaosRunState.VERIFIED,
            ChaosRunState.STOP_TRIGGERED,
            ChaosRunState.RECOVERING,
            ChaosRunState.VERIFYING,
        }:
            return await self._recover_resumed(
                run_id=run_id,
                decision=decision,
                state=state,
                recovery_plan=recovery_plan,
            )
        if not decision.eligible:
            state = await self._advance(state, ChaosRunState.DENIED)
            return GovernedChaosRunResult(run_id, decision, state, None, None, None)

        pre_injection_states = (
            ChaosRunState.IMPACT_CHECKED,
            ChaosRunState.DRY_RUN_VERIFIED,
            ChaosRunState.APPROVED,
            ChaosRunState.INJECTING,
            ChaosRunState.OBSERVING,
        )
        current_index = (
            pre_injection_states.index(state.state) if state.state in pre_injection_states else -1
        )
        for target_state in pre_injection_states[current_index + 1 :]:
            state = await self._advance(state, target_state)

        experiment: ExperimentResult
        try:
            experiment = await self._harness.run(
                scenario,
                approved_targets=eligibility_context.explicit_targets,
                mode=Mode.ENFORCE,
                impact_guard=impact_guard,
                guard_interval_seconds=guard_interval_seconds,
            )
        except asyncio.CancelledError:
            state = await self._advance(state, ChaosRunState.STOP_TRIGGERED)
            state = await self._advance(state, ChaosRunState.RECOVERING)
            await self._recover_and_verify(state=state, plan=recovery_plan, fault_reverted=True)
            raise

        if not experiment.injected and experiment.outcome is ExperimentOutcome.ABORTED:
            state = await self._advance(state, ChaosRunState.FAILED)
            return GovernedChaosRunResult(run_id, decision, state, experiment, None, None)
        if experiment.stop_reason or experiment.outcome is ExperimentOutcome.ABORTED:
            state = await self._advance(state, ChaosRunState.STOP_TRIGGERED)
        elif experiment.outcome is ExperimentOutcome.ROLLBACK_FAILED:
            state = await self._advance(state, ChaosRunState.FAILED)
            return GovernedChaosRunResult(run_id, decision, state, experiment, None, None)
        else:
            state = await self._advance(state, ChaosRunState.VERIFIED)
        state = await self._advance(state, ChaosRunState.RECOVERING)
        state, recovery, verification = await self._recover_and_verify(
            state=state,
            plan=recovery_plan,
            fault_reverted=experiment.reverted,
        )
        return GovernedChaosRunResult(run_id, decision, state, experiment, recovery, verification)

    async def _recover_resumed(
        self,
        *,
        run_id: str,
        decision: ChaosEligibilityDecision,
        state: ChaosRunSnapshot,
        recovery_plan: RecoveryPlanRecord,
    ) -> GovernedChaosRunResult:
        if state.state in {ChaosRunState.INJECTING, ChaosRunState.OBSERVING}:
            state = await self._advance(state, ChaosRunState.STOP_TRIGGERED)
        if state.state in {ChaosRunState.VERIFIED, ChaosRunState.STOP_TRIGGERED}:
            state = await self._advance(state, ChaosRunState.RECOVERING)
        state, recovery, verification = await self._recover_and_verify(
            state=state,
            plan=recovery_plan,
            fault_reverted=True,
        )
        return GovernedChaosRunResult(run_id, decision, state, None, recovery, verification)

    async def _recover_and_verify(
        self,
        *,
        state: ChaosRunSnapshot,
        plan: RecoveryPlanRecord,
        fault_reverted: bool,
    ) -> tuple[ChaosRunSnapshot, RecoveryControlResult, RecoveryVerification]:
        recovery = await self._execute_recovery(plan)
        if state.state is ChaosRunState.RECOVERING:
            state = await self._advance(state, ChaosRunState.VERIFYING)
        probe_results, telemetry_complete = await self._evidence_collector.collect(plan)
        verification = verify_recovery_postconditions(
            probe_results,
            telemetry_complete=telemetry_complete,
        )
        recovered = (
            recovery.succeeded
            and fault_reverted
            and verification.outcome is RecoveryVerificationOutcome.RECOVERED
        )
        state = await self._advance(
            state,
            ChaosRunState.RECOVERED if recovered else ChaosRunState.ESCALATED,
        )
        return state, recovery, verification

    async def _execute_recovery(self, plan: RecoveryPlanRecord) -> RecoveryControlResult:
        return await self._recovery.execute(
            plan,
            target_ids=plan.direct_target_ids,
            now=self._now(),
        )

    async def _advance(
        self,
        state: ChaosRunSnapshot,
        target: ChaosRunState,
    ) -> ChaosRunSnapshot:
        return await self._run_store.transition(
            state,
            target=target,
            idempotency_key=f"{state.run_id}:{target.value}",
            at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("governed chaos clock MUST be timezone-aware")
        return value


__all__ = ["GovernedChaosRunner", "GovernedChaosRunResult"]
