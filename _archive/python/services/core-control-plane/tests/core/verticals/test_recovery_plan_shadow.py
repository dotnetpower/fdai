"""Provider-neutral shadow recovery ordering and fencing invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.verticals.resilience.recovery_plan import (
    RecoveryMode,
    RecoveryObjectives,
    RecoveryPlan,
    RecoveryProfile,
    RecoveryState,
)
from fdai.core.verticals.resilience.shadow_recovery import (
    ShadowRecoveryError,
    ShadowRecoveryOrchestrator,
    ShadowRecoveryOutcome,
)
from fdai.shared.providers.control_plane_recovery import (
    RegionalRecoveryAction,
    RegionalRecoveryShadowReceipt,
    RegionalRecoveryShadowRequest,
)

_REPLAY_START = datetime(2026, 8, 24, tzinfo=UTC)
_REPLAY_END = _REPLAY_START + timedelta(minutes=5)
_WRITER_STATES = {
    RegionalRecoveryAction.PROVISION_RECOVERY_REGION: (True, False),
    RegionalRecoveryAction.FENCE_PRIMARY: (False, False),
    RegionalRecoveryAction.REPLAY_EVENTS: (False, False),
    RegionalRecoveryAction.SHIFT_TRAFFIC: (False, True),
    RegionalRecoveryAction.FAILBACK: (True, False),
}


class _FakeRegionalRecoveryProvider:
    def __init__(
        self,
        *,
        fail_action: RegionalRecoveryAction | None = None,
        second_writer_action: RegionalRecoveryAction | None = None,
    ) -> None:
        self.fail_action = fail_action
        self.second_writer_action = second_writer_action
        self.requests: list[RegionalRecoveryShadowRequest] = []

    async def evaluate_shadow(
        self,
        request: RegionalRecoveryShadowRequest,
    ) -> RegionalRecoveryShadowReceipt:
        self.requests.append(request)
        primary_writer, recovery_writer = _WRITER_STATES[request.action]
        if request.action is self.second_writer_action:
            primary_writer = True
            recovery_writer = True
        return RegionalRecoveryShadowReceipt(
            action=request.action,
            succeeded=request.action is not self.fail_action,
            observed_epoch=request.recovery_epoch,
            primary_writer_active=primary_writer,
            recovery_writer_active=recovery_writer,
            evidence_refs=(f"evidence://shadow/{request.action.value}",),
        )


def _plan(*, state: RecoveryState, recovery_epoch: int) -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="regional-shadow-recovery",
        revision=3,
        mode=RecoveryMode.DRILL,
        profile=RecoveryProfile.RESTORE,
        primary_region="primary-region",
        recovery_region="recovery-region",
        requester_ref="group:requesters",
        scope=("control-plane", "state-store", "event-bus"),
        objectives=RecoveryObjectives(300, 900, 1800),
        stop_conditions=("fence_unverified", "second_writer_active"),
        rollback_ref="runbook://control-plane-failover",
        max_affected_resources=4,
        state=state,
        recovery_epoch=recovery_epoch,
    )


async def test_shadow_failover_calls_provider_in_safe_order() -> None:
    provider = _FakeRegionalRecoveryProvider()
    plan = _plan(state=RecoveryState.ACTIVATING, recovery_epoch=7)

    result = await ShadowRecoveryOrchestrator(provider).evaluate_failover(
        plan,
        expected_recovery_epoch=7,
        replay_start=_REPLAY_START,
        replay_end=_REPLAY_END,
    )

    assert result.outcome is ShadowRecoveryOutcome.COMPLETED
    assert [request.action for request in provider.requests] == [
        RegionalRecoveryAction.PROVISION_RECOVERY_REGION,
        RegionalRecoveryAction.FENCE_PRIMARY,
        RegionalRecoveryAction.REPLAY_EVENTS,
        RegionalRecoveryAction.SHIFT_TRAFFIC,
    ]
    assert all(request.plan_revision == 3 for request in provider.requests)
    assert all(request.recovery_epoch == 7 for request in provider.requests)
    assert all(request.replay_start == _REPLAY_START for request in provider.requests)
    assert plan.state is RecoveryState.ACTIVATING


async def test_shadow_failover_rejects_stale_epoch_before_provider_call() -> None:
    provider = _FakeRegionalRecoveryProvider()

    with pytest.raises(ShadowRecoveryError, match="stale recovery epoch"):
        await ShadowRecoveryOrchestrator(provider).evaluate_failover(
            _plan(state=RecoveryState.ACTIVATING, recovery_epoch=7),
            expected_recovery_epoch=6,
            replay_start=_REPLAY_START,
            replay_end=_REPLAY_END,
        )

    assert provider.requests == []


async def test_shadow_failover_rejects_inverted_replay_window() -> None:
    provider = _FakeRegionalRecoveryProvider()

    with pytest.raises(ShadowRecoveryError, match="replay_end"):
        await ShadowRecoveryOrchestrator(provider).evaluate_failover(
            _plan(state=RecoveryState.ACTIVATING, recovery_epoch=7),
            expected_recovery_epoch=7,
            replay_start=_REPLAY_END,
            replay_end=_REPLAY_START,
        )

    assert provider.requests == []


async def test_shadow_failover_halts_after_intermediate_failure() -> None:
    provider = _FakeRegionalRecoveryProvider(fail_action=RegionalRecoveryAction.REPLAY_EVENTS)

    result = await ShadowRecoveryOrchestrator(provider).evaluate_failover(
        _plan(state=RecoveryState.ACTIVATING, recovery_epoch=7),
        expected_recovery_epoch=7,
        replay_start=_REPLAY_START,
        replay_end=_REPLAY_END,
    )

    assert result.outcome is ShadowRecoveryOutcome.HALTED
    assert result.halted_action is RegionalRecoveryAction.REPLAY_EVENTS
    assert result.halt_reason == "provider_reported_failure"
    assert [request.action for request in provider.requests] == [
        RegionalRecoveryAction.PROVISION_RECOVERY_REGION,
        RegionalRecoveryAction.FENCE_PRIMARY,
        RegionalRecoveryAction.REPLAY_EVENTS,
    ]


async def test_shadow_failover_halts_when_second_writer_is_observed() -> None:
    provider = _FakeRegionalRecoveryProvider(
        second_writer_action=RegionalRecoveryAction.FENCE_PRIMARY
    )

    result = await ShadowRecoveryOrchestrator(provider).evaluate_failover(
        _plan(state=RecoveryState.ACTIVATING, recovery_epoch=7),
        expected_recovery_epoch=7,
        replay_start=_REPLAY_START,
        replay_end=_REPLAY_END,
    )

    assert result.outcome is ShadowRecoveryOutcome.HALTED
    assert result.halted_action is RegionalRecoveryAction.FENCE_PRIMARY
    assert result.halt_reason == "second_writer_active"
    assert len(provider.requests) == 2


@pytest.mark.parametrize(
    (
        "primary_ready",
        "state_reconciled",
        "primary_writer_active",
        "recovery_writer_active",
        "message",
    ),
    [
        (False, True, False, True, "verified primary"),
        (True, False, False, True, "reconciled state"),
        (True, True, True, True, "sole active writer"),
        (True, True, False, False, "sole active writer"),
    ],
)
async def test_shadow_failback_requires_all_prerequisites(
    primary_ready: bool,
    state_reconciled: bool,
    primary_writer_active: bool,
    recovery_writer_active: bool,
    message: str,
) -> None:
    provider = _FakeRegionalRecoveryProvider()

    with pytest.raises(ShadowRecoveryError, match=message):
        await ShadowRecoveryOrchestrator(provider).evaluate_failback(
            _plan(state=RecoveryState.FAILING_BACK, recovery_epoch=8),
            expected_recovery_epoch=8,
            previous_recovery_epoch=7,
            replay_start=_REPLAY_START,
            replay_end=_REPLAY_END,
            primary_ready=primary_ready,
            state_reconciled=state_reconciled,
            primary_writer_active=primary_writer_active,
            recovery_writer_active=recovery_writer_active,
        )

    assert provider.requests == []


async def test_shadow_failback_requires_new_epoch_and_restores_one_writer() -> None:
    provider = _FakeRegionalRecoveryProvider()
    orchestrator = ShadowRecoveryOrchestrator(provider)
    plan = _plan(state=RecoveryState.FAILING_BACK, recovery_epoch=8)

    with pytest.raises(ShadowRecoveryError, match="stale recovery epoch"):
        await orchestrator.evaluate_failback(
            plan,
            expected_recovery_epoch=7,
            previous_recovery_epoch=7,
            replay_start=_REPLAY_START,
            replay_end=_REPLAY_END,
            primary_ready=True,
            state_reconciled=True,
            primary_writer_active=False,
            recovery_writer_active=True,
        )
    with pytest.raises(ShadowRecoveryError, match="new recovery epoch"):
        await orchestrator.evaluate_failback(
            plan,
            expected_recovery_epoch=8,
            previous_recovery_epoch=8,
            replay_start=_REPLAY_START,
            replay_end=_REPLAY_END,
            primary_ready=True,
            state_reconciled=True,
            primary_writer_active=False,
            recovery_writer_active=True,
        )
    result = await orchestrator.evaluate_failback(
        plan,
        expected_recovery_epoch=8,
        previous_recovery_epoch=7,
        replay_start=_REPLAY_START,
        replay_end=_REPLAY_END,
        primary_ready=True,
        state_reconciled=True,
        primary_writer_active=False,
        recovery_writer_active=True,
    )

    assert result.outcome is ShadowRecoveryOutcome.COMPLETED
    assert [request.action for request in provider.requests] == [RegionalRecoveryAction.FAILBACK]
    assert result.receipts[0].primary_writer_active is True
    assert result.receipts[0].recovery_writer_active is False
