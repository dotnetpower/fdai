from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.chaos import (
    ChaosEligibilityContext,
    ChaosRunState,
    FaultInjectionHarness,
    FaultScenario,
    GovernedChaosRunner,
    ShadowFaultInjector,
)
from fdai.core.chaos.run_store import ChaosRunStore
from fdai.core.recovery import (
    PreauthorizedRecoveryController,
    ProbeVerdict,
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryStrategy,
    RecoveryVerificationOutcome,
    compile_recovery_plan,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


class _Probe:
    async def observed(self, **_kwargs: object) -> bool:
        return True


class _Dispatcher:
    def __init__(self, *, fail: bool = False, raises: bool = False) -> None:
        self.fail = fail
        self.raises = raises
        self.calls: list[str] = []

    async def dispatch(self, action: RecoveryAction, *, idempotency_key: str) -> str | None:
        self.calls.append(action.action_id)
        if self.raises:
            raise RuntimeError("provider unavailable")
        return None if self.fail else f"receipt:{idempotency_key}"


class _EvidenceCollector:
    def __init__(
        self,
        *,
        omit: RecoveryProbeKind | None = None,
        raises: bool = False,
    ) -> None:
        self.omit = omit
        self.raises = raises

    async def collect(
        self,
        _plan: RecoveryPlanRecord,
    ) -> tuple[tuple[RecoveryProbeResult, ...], bool]:
        if self.raises:
            raise RuntimeError("telemetry unavailable")
        return (
            tuple(
                RecoveryProbeResult(
                    kind=kind,
                    verdict=ProbeVerdict.PASSED,
                    observed_at=_NOW,
                    evidence_ref=f"evidence:{kind.value}",
                )
                for kind in RecoveryProbeKind
                if kind is not self.omit
            ),
            True,
        )


def _plan() -> RecoveryPlanRecord:
    action = RecoveryAction(
        action_id="restore",
        action_type_ref="ops.restore-service",
        action_type_version="1.0.0",
        target_ref="resource-a",
        compensation_action_type_ref="ops.undo-restore",
        stop_conditions=("time_box",),
        rollback_ref="rollback:restore",
    )
    return compile_recovery_plan(
        strategy=RecoveryStrategy.STATE_FORWARD,
        workflow_ref="recover-service",
        workflow_version="1.0.0",
        catalog_digest="catalog-1",
        actions=(action,),
        impact_envelope_id="impact-1",
        recovery_objective_ref="rto-1",
        verification_probes=("health",),
        direct_target_ids=("resource-a",),
        graph_revision="graph-1",
        dry_run_receipt="dry-run-1",
        last_rehearsed_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )


def _eligibility(**overrides: object) -> ChaosEligibilityContext:
    values: dict[str, object] = {
        "catalog_valid": True,
        "scenario_promoted": True,
        "action_types_promoted": True,
        "causal_hypothesis_ref": "causal-1",
        "refutation_query_ref": "query-1",
        "explicit_targets": ("resource-a",),
        "supported_environment": True,
        "owner_ref": "owner-1",
        "maintenance_window_active": True,
        "graph_complete": True,
        "objective_headroom": True,
        "recovery_ready": True,
        "telemetry_ready": True,
        "no_conflicting_work": True,
        "dry_run_receipt": "dry-run-1",
        "locks_acquired": True,
        "idempotency_key": "run-1",
        "kill_switch_clear": True,
        "stop_conditions_ready": True,
        "audit_ready": True,
        "approval_principal": "Var",
        "approver_ids": ("approver-a",),
        "initiator_id": "initiator-a",
    }
    values.update(overrides)
    return ChaosEligibilityContext(**values)  # type: ignore[arg-type]


def _scenario() -> FaultScenario:
    return FaultScenario(
        scenario_id="pod-kill",
        fault_type="pod_kill",
        description="bounded pod kill",
        target_selector="demo",
        expected_signal="pod_restart",
        blast_radius_cap=1,
        duration_seconds=1,
    )


async def _guard(_elapsed: float):  # type: ignore[no-untyped-def]
    return None


async def _sleeper(_seconds: float) -> None:
    return None


def _runner(
    injector: ShadowFaultInjector,
    dispatcher: _Dispatcher,
    *,
    evidence_collector: _EvidenceCollector | None = None,
) -> GovernedChaosRunner:
    return GovernedChaosRunner(
        harness=FaultInjectionHarness(
            injectors=(injector,),
            probe=_Probe(),
            sleeper=_sleeper,
        ),
        run_store=ChaosRunStore(state_store=InMemoryStateStore()),
        recovery=PreauthorizedRecoveryController(dispatcher=dispatcher),
        evidence_collector=evidence_collector or _EvidenceCollector(),
        clock=lambda: _NOW,
    )


async def test_governed_runner_reaches_recovered_after_guarded_enforce() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher()
    result = await _runner(injector, dispatcher).run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )
    assert result.state.state is ChaosRunState.RECOVERED
    assert result.experiment is not None and result.experiment.reverted
    assert result.recovery is not None and result.recovery.succeeded
    assert result.verification is not None
    assert result.verification.outcome is RecoveryVerificationOutcome.RECOVERED
    assert dispatcher.calls == ["restore"]


async def test_governed_runner_denies_before_injection() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher()
    result = await _runner(injector, dispatcher).run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(graph_complete=False),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )
    assert result.state.state is ChaosRunState.DENIED
    assert injector.injected == []
    assert dispatcher.calls == []


async def test_governed_runner_escalates_when_recovery_receipt_is_missing() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher(fail=True)
    result = await _runner(injector, dispatcher).run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )
    assert result.state.state is ChaosRunState.ESCALATED
    assert result.recovery is not None and not result.recovery.succeeded


async def test_governed_runner_resumes_observing_with_recovery_not_reinjection() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher()
    state_store = InMemoryStateStore()
    run_store = ChaosRunStore(state_store=state_store)
    snapshot = await run_store.create(run_id="run-1", at=_NOW)
    for state in (
        ChaosRunState.IMPACT_CHECKED,
        ChaosRunState.DRY_RUN_VERIFIED,
        ChaosRunState.APPROVED,
        ChaosRunState.INJECTING,
        ChaosRunState.OBSERVING,
    ):
        snapshot = await run_store.transition(
            snapshot,
            target=state,
            idempotency_key=f"run-1:{state.value}",
            at=_NOW,
        )
    runner = GovernedChaosRunner(
        harness=FaultInjectionHarness(
            injectors=(injector,),
            probe=_Probe(),
            sleeper=_sleeper,
        ),
        run_store=run_store,
        recovery=PreauthorizedRecoveryController(dispatcher=dispatcher),
        evidence_collector=_EvidenceCollector(),
        clock=lambda: _NOW,
    )

    result = await runner.run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )

    assert result.state.state is ChaosRunState.RECOVERED
    assert result.experiment is None
    assert injector.injected == []
    assert dispatcher.calls == ["restore"]


async def test_governed_runner_denies_stale_pre_injection_resume() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher()
    state_store = InMemoryStateStore()
    run_store = ChaosRunStore(state_store=state_store)
    snapshot = await run_store.create(run_id="run-1", at=_NOW)
    await run_store.transition(
        snapshot,
        target=ChaosRunState.IMPACT_CHECKED,
        idempotency_key="run-1:impact_checked",
        at=_NOW,
    )
    runner = GovernedChaosRunner(
        harness=FaultInjectionHarness(injectors=(injector,), probe=_Probe(), sleeper=_sleeper),
        run_store=run_store,
        recovery=PreauthorizedRecoveryController(dispatcher=dispatcher),
        evidence_collector=_EvidenceCollector(),
        clock=lambda: _NOW,
    )

    result = await runner.run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(graph_complete=False),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )

    assert result.state.state is ChaosRunState.DENIED
    assert injector.injected == []
    assert dispatcher.calls == []


async def test_governed_runner_escalates_when_recovery_evidence_is_incomplete() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    dispatcher = _Dispatcher()
    runner = _runner(
        injector,
        dispatcher,
        evidence_collector=_EvidenceCollector(omit=RecoveryProbeKind.RECURRENCE_CLEAR),
    )

    result = await runner.run_enforce(
        run_id="run-1",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )

    assert result.state.state is ChaosRunState.ESCALATED
    assert result.recovery is not None and result.recovery.succeeded
    assert result.verification is not None
    assert result.verification.outcome is RecoveryVerificationOutcome.UNSCORABLE


async def test_governed_runner_escalates_provider_failures() -> None:
    dispatcher_result = await _runner(
        ShadowFaultInjector(fault_type="pod_kill"),
        _Dispatcher(raises=True),
    ).run_enforce(
        run_id="dispatcher-failure",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )
    assert dispatcher_result.state.state is ChaosRunState.ESCALATED
    assert dispatcher_result.recovery is not None
    assert dispatcher_result.recovery.reason == "recovery dispatcher failed: RuntimeError"

    evidence_result = await _runner(
        ShadowFaultInjector(fault_type="pod_kill"),
        _Dispatcher(),
        evidence_collector=_EvidenceCollector(raises=True),
    ).run_enforce(
        run_id="evidence-failure",
        scenario=_scenario(),
        eligibility_context=_eligibility(),
        recovery_plan=_plan(),
        impact_guard=_guard,
    )
    assert evidence_result.state.state is ChaosRunState.ESCALATED
    assert evidence_result.verification is not None
    assert evidence_result.verification.outcome is RecoveryVerificationOutcome.UNSCORABLE
