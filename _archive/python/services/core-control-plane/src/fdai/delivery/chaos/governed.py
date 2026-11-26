"""Governed chaos execution adapter over the durable governed runner.

:class:`GovernedChaosExecutionAdapter` is the only live-injection path for a
catalog chaos scenario. It satisfies
:class:`~fdai.delivery.chaos.tool.GovernedChaosExecution` and delegates every
enforce request to :class:`~fdai.core.chaos.runner.GovernedChaosRunner` over a
StateStore-backed :class:`~fdai.core.chaos.run_store.ChaosRunStore`.

- **Idempotency and restart:** The run id derives from the request idempotency
  key, scenario, and target set. A terminal run replays its recorded outcome,
  an interrupted run resumes recovery instead of injecting again, and only the
  writer whose compare-and-swap applies ``injecting`` may run the harness.
- **Targets:** A distributed logical-target lock and a durable per-target claim
  keep one live run per target. An escalated, failed-after-injection, or
  orphaned run keeps its targets until an audited human closure releases them.
  A closed run never resumes, and the exclusive ``injecting`` transition
  re-checks closure. Each target must be exactly the resource the injector
  mutates for it.
- **Authority:** Promotion, approval, the ActionType tier ceiling, locks,
  idempotency, and audit readiness come only from their authoritative sources,
  and the deterministic eligibility gate decides. A request-supplied approval
  reference is only a claim.
- **Fail closed:** A missing or failing collaborator denies the run before
  injection or escalates an in-flight run for manual recovery. Nothing falls
  back to a raw harness run.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.run_store import ChaosRunClaimError
from fdai.core.chaos.runner import GovernedChaosRunner, GovernedChaosRunResult
from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint
from fdai.core.recovery import PreauthorizedRecoveryController
from fdai.delivery.chaos.governed_bindings import (
    CHAOS_ENFORCE_INTENT,
    ChaosApprovalEvidence,
    ChaosRunPlan,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.governed_claims import (
    ChaosRunClosedError,
    ChaosTargetClaims,
    ClosureFencedRunStore,
    held_target_locks,
)
from fdai.delivery.chaos.governed_eligibility import EligibilityInputs, eligibility_context
from fdai.delivery.chaos.governed_outcome import (
    GovernedChaosOutcome,
    closed_outcome,
    governed_outcome,
    outcome_record,
    outcome_record_key,
    refused_outcome,
    replayed_outcome,
)
from fdai.delivery.chaos.governed_records import (
    CHAOS_ACTION_TYPE,
    PRE_INJECTION_STATES,
    AuditedExperimentRecorder,
    admit_chaos_request,
    escalation_audit_entry,
    governed_chaos_run_id,
    time_box_seconds,
)
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
)

_LOGGER = logging.getLogger(__name__)


class GovernedChaosExecutionAdapter:
    """Run one approved catalog chaos enforce request through the governed runner."""

    def __init__(
        self,
        *,
        entries: Sequence[CatalogEntry],
        promoted_ids: frozenset[str],
        factory: ScenarioFactory,
        context: Mapping[str, Any],
        bindings: GovernedChaosBindings,
        action_type: OntologyActionType,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        operation_timeout_seconds: float = 180.0,
        rollback_timeout_seconds: float = 180.0,
        max_hold_seconds: float = 600.0,
        guard_interval_seconds: float = 5.0,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(bindings, GovernedChaosBindings):
            raise TypeError("governed chaos execution requires GovernedChaosBindings")
        if action_type.name != CHAOS_ACTION_TYPE:
            raise ValueError(
                f"governed chaos execution requires the {CHAOS_ACTION_TYPE} ActionType"
            )
        bounds = (
            operation_timeout_seconds,
            rollback_timeout_seconds,
            max_hold_seconds,
            guard_interval_seconds,
            lock_timeout_seconds,
        )
        if min(bounds) <= 0:
            raise ValueError("governed chaos timeouts and intervals MUST be positive")
        self._entries = {entry.id: entry for entry in entries}
        self._fingerprint = catalog_fingerprint(list(entries))
        self._promoted_ids = promoted_ids
        self._factory = factory
        self._context = dict(context)
        self._bindings = bindings
        self._action_type = action_type
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._sleeper = sleeper
        self._operation_timeout = operation_timeout_seconds
        self._rollback_timeout = rollback_timeout_seconds
        self._max_hold = max_hold_seconds
        self._guard_interval = guard_interval_seconds
        self._lock_timeout = lock_timeout_seconds
        self._run_store = ClosureFencedRunStore(state_store=bindings.state_store)
        self._claims = ChaosTargetClaims(
            state_store=bindings.state_store, run_store=self._run_store
        )
        self._recovery = PreauthorizedRecoveryController(dispatcher=bindings.recovery_dispatcher)

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        """Satisfy ``GovernedChaosExecution``; see :meth:`run` for the contract."""

        return (await self.run(request)).receipt

    async def run(self, request: ToolCallRequest) -> GovernedChaosOutcome:
        """Run, replay, or resume the governed run bound to ``request``.

        Raises:
            ToolPromotionError: the request is not a labeled enforce request.
            ToolPreconditionError: the request is malformed, exceeds the
                scenario blast radius, or the target locks are unavailable.

        Denials and a lost injection claim return ``PRECONDITION_FAILED``. Only
        verified recovery returns ``SUCCEEDED``, and the outcome reports the
        detection verdict separately. Cancellation propagates after the
        runner's recovery path.
        """

        entry, scenario, targets = admit_chaos_request(request, self._entries)
        run_id = governed_chaos_run_id(request.idempotency_key, entry.id, targets)
        async with held_target_locks(
            self._bindings.target_lock,
            targets,
            timeout=self._lock_timeout,
        ):
            existing = await self._run_store.get(run_id)
            if existing is not None and await self._claims.closed(run_id):
                return closed_outcome(existing)
            if existing is not None and existing.state.terminal:
                return await self._replay(existing)
            plan = await self._plan(run_id, scenario, targets)
            if plan is None:
                return await self._without_plan(run_id, existing)
            snapshot = existing or await self._run_store.create(run_id=run_id, at=self._now())
            if snapshot.state.terminal:
                return await self._replay(snapshot)
            built = self._build(entry)
            approval = await self._approval(request, run_id)
            await self._claims.bind(
                run_id=run_id,
                targets=targets,
                approval_ref=(
                    approval.approval_ref
                    if approval is not None
                    else request.metadata.get("approval_ref")
                ),
                at=self._now(),
            )
            claimed = await self._claims.claim(run_id=run_id, targets=targets, at=self._now())
            inputs = EligibilityInputs(
                request=request,
                entry=entry,
                targets=targets,
                plan=plan,
                built=built,
                approval=approval,
                targets_claimed=claimed,
                now=self._now(),
            )
            context = await eligibility_context(
                inputs,
                bindings=self._bindings,
                action_type=self._action_type,
                promoted_ids=self._promoted_ids,
                catalog_fingerprint=self._fingerprint,
            )
            runner = GovernedChaosRunner(
                harness=self._harness(request, run_id, built),
                run_store=self._run_store,
                recovery=self._recovery,
                evidence_collector=self._bindings.evidence_collector,
                clock=self._now,
            )
            try:
                result = await runner.run_enforce(
                    run_id=run_id,
                    scenario=scenario,
                    eligibility_context=context,
                    recovery_plan=plan.recovery_plan,
                    impact_guard=plan.impact_guard,
                    guard_interval_seconds=self._guard_interval,
                )
            except ChaosRunClaimError as exc:
                detail = (
                    "conflict:run_closed"
                    if isinstance(exc, ChaosRunClosedError)
                    else "conflict:injection_claimed"
                )
                receipt = ToolCallReceipt(
                    outcome=ToolCallOutcome.PRECONDITION_FAILED,
                    receipt_ref=run_id,
                    detail=detail,
                )
                return refused_outcome(receipt, run_state=None)
            await self._record_outcome(result)
        return governed_outcome(result)

    async def _plan(
        self,
        run_id: str,
        scenario: FaultScenario,
        targets: tuple[str, ...],
    ) -> ChaosRunPlan | None:
        try:
            plan = await self._bindings.planner.plan(
                run_id=run_id,
                scenario=scenario,
                targets=targets,
            )
        except Exception as exc:  # noqa: BLE001 - an unavailable plan never injects
            _LOGGER.warning(
                "governed_chaos_plan_unavailable",
                extra={"run_id": run_id, "error_type": type(exc).__name__},
            )
            return None
        return plan if isinstance(plan, ChaosRunPlan) else None

    async def _approval(
        self,
        request: ToolCallRequest,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        try:
            evidence = await self._bindings.approval_verifier.verify(request, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 - unverifiable approval denies the run
            _LOGGER.warning(
                "governed_chaos_approval_unverified",
                extra={"run_id": run_id, "error_type": type(exc).__name__},
            )
            return None
        if not isinstance(evidence, ChaosApprovalEvidence):
            return None
        claim = request.metadata.get("approval_ref")
        if (
            evidence.intent != CHAOS_ENFORCE_INTENT
            or evidence.run_id not in (None, run_id)
            or not evidence.approval_ref.strip()
            or not evidence.initiator_id.strip()
            or (claim is not None and claim != evidence.approval_ref)
        ):
            return None
        return evidence

    def _build(self, entry: CatalogEntry) -> tuple[FaultInjector, SignalProbe] | None:
        if not self._factory.is_executable(entry):
            return None
        try:
            return self._factory.build(entry, dict(self._context))
        except Exception as exc:  # noqa: BLE001 - an unbuildable scenario is catalog-invalid
            _LOGGER.warning(
                "governed_chaos_scenario_unbuildable",
                extra={"scenario_id": entry.id, "error_type": type(exc).__name__},
            )
            return None

    def _harness(
        self,
        request: ToolCallRequest,
        run_id: str,
        built: tuple[FaultInjector, SignalProbe] | None,
    ) -> FaultInjectionHarness:
        time_box = time_box_seconds(request)
        return FaultInjectionHarness(
            injectors=(built[0],) if built is not None else (),
            probe=built[1] if built is not None else None,
            recorder=AuditedExperimentRecorder(self._bindings.state_store, run_id=run_id),
            sleeper=self._sleeper,
            wall_clock=self._now,
            operation_timeout_seconds=self._operation_timeout,
            rollback_timeout_seconds=self._rollback_timeout,
            max_hold_seconds=min(self._max_hold, time_box) if time_box else self._max_hold,
        )

    async def _replay(self, snapshot: ChaosRunSnapshot) -> GovernedChaosOutcome:
        try:
            record = await self._bindings.state_store.read_state(
                outcome_record_key(snapshot.run_id)
            )
        except Exception:  # noqa: BLE001 - an unreadable record leaves detection unknown
            _LOGGER.warning("governed_chaos_outcome_unreadable", extra={"run_id": snapshot.run_id})
            record = None
        return replayed_outcome(snapshot, record)

    async def _record_outcome(self, result: GovernedChaosRunResult) -> None:
        if not result.state.state.terminal:
            return
        try:
            await self._bindings.state_store.write_state_if_absent(
                outcome_record_key(result.run_id),
                outcome_record(result),
            )
        except Exception:  # noqa: BLE001 - a replay then reports detection as unknown
            _LOGGER.error("governed_chaos_outcome_unrecorded", extra={"run_id": result.run_id})

    async def _without_plan(
        self,
        run_id: str,
        existing: ChaosRunSnapshot | None,
    ) -> GovernedChaosOutcome:
        """Deny a pre-injection run, or escalate an in-flight run that cannot recover."""

        snapshot = existing or await self._run_store.create(run_id=run_id, at=self._now())
        if snapshot.state.terminal:
            return await self._replay(snapshot)
        if snapshot.state in PRE_INJECTION_STATES:
            denied = await self._run_store.transition(
                snapshot,
                target=ChaosRunState.DENIED,
                idempotency_key=f"{run_id}:{ChaosRunState.DENIED.value}",
                at=self._now(),
            )
            receipt = ToolCallReceipt(
                outcome=ToolCallOutcome.PRECONDITION_FAILED,
                receipt_ref=run_id,
                detail="denied:run_plan_unavailable",
            )
            return refused_outcome(receipt, run_state=denied.state.value)
        await self._audit_escalation(snapshot, reason="run_plan_unavailable")
        receipt = ToolCallReceipt(
            outcome=ToolCallOutcome.FAILED,
            receipt_ref=run_id,
            rollback_succeeded=False,
            detail=f"escalated:run_plan_unavailable:{snapshot.state.value}",
        )
        return refused_outcome(receipt, run_state=snapshot.state.value)

    async def _audit_escalation(self, snapshot: ChaosRunSnapshot, *, reason: str) -> None:
        entry = escalation_audit_entry(snapshot, reason=reason, recorded_at=self._now())
        try:
            await self._bindings.state_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - the returned receipt still escalates
            _LOGGER.error(
                "governed_chaos_escalation_audit_failed", extra={"run_id": snapshot.run_id}
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("governed chaos clock MUST be timezone-aware")
        return value


__all__ = [
    "CHAOS_ACTION_TYPE",
    "GovernedChaosExecutionAdapter",
    "GovernedChaosOutcome",
]
