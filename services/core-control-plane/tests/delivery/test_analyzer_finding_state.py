from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.analyzer_finding_receipt import AnalyzerFindingReceipt, AnalyzerPublicationStatus
from fdai.delivery.analyzer_finding_state import AnalyzerFindingStateStore
from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerReceiptStore
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.finding_state import (
    FINDING_STATE_PREFIX,
    FindingState,
    finding_identity,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def receipt(number: int = 0, **changes: object) -> AnalyzerFindingReceipt:
    value = AnalyzerFindingReceipt(
        idempotency_key=f"observation:{number}",
        signal="host_cpu",
        detection_latency_seconds=0,
        evidence_complete=True,
        publication=AnalyzerPublicationStatus.PUBLISHED,
        recovery_closed=False,
        evidence_refs=("metric:sample",),
        resource_ref="resource:example",
        resource_kind="virtual_machine",
        occurred_at=NOW + timedelta(minutes=number),
        recorded_at=NOW + timedelta(minutes=number),
        assessed_by="host_cpu_threshold",
        assessment_status="cpu_threshold_observed",
        severity=Severity.MEDIUM,
        observation="CPU exceeds its configured threshold",
    )
    return replace(value, **changes)


async def current(state: InMemoryStateStore, signal: str = "host_cpu") -> FindingState:
    key = FINDING_STATE_PREFIX + finding_identity("virtual_machine", "resource:example", signal)
    return FindingState.model_validate(await state.read_state(key))


async def test_repeated_observations_do_not_repeat_alert_but_escalation_does() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt())
    await store.record(receipt(1))
    repeated = await current(state)
    assert repeated.revision == 2
    assert repeated.notification_version == 1
    await store.record(receipt(2, severity=Severity.CRITICAL))
    escalated = await current(state)
    assert escalated.notification_version == 2
    assert escalated.notification_reason == "escalated"


async def test_verified_recovery_then_reopening_is_a_new_notification() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt())
    await store.record(receipt(1, recovery_closed=True))
    resolved = await current(state)
    assert resolved.status == "resolved"
    assert resolved.notification_reason == "recovered"
    assert resolved.notification_version == 2
    await store.record(receipt(2))
    reopened = await current(state)
    assert reopened.status == "active"
    assert reopened.notification_version == 3
    assert reopened.notification_reason == "opened"


async def test_no_routine_healthy_finding_and_no_failed_publication_projection() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt(recovery_closed=True))
    await store.record(receipt(publication=AnalyzerPublicationStatus.UNCERTAIN))
    assert not await state.read_states(FINDING_STATE_PREFIX, limit=100)


async def test_incomplete_recovery_is_rejected_without_erasing_active_state() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt())
    with pytest.raises(ValueError, match="complete canonical assessment"):
        await store.record(receipt(1, evidence_complete=False, recovery_closed=True))
    assert (await current(state)).status == "active"


async def test_stale_replay_and_same_identity_are_noops_but_conflicts_fail() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt(2))
    await store.record(receipt(1, recovery_closed=True))
    await store.record(receipt(2))
    assert (await current(state)).revision == 1
    with pytest.raises(ValueError, match="identity collision"):
        await store.record(receipt(2, severity=Severity.CRITICAL))


async def test_signals_on_one_resource_and_history_eviction_remain_independent() -> None:
    state = InMemoryStateStore()
    store = StateStoreAnalyzerReceiptStore(state, retain_newest=1)
    await store.record(receipt())
    await store.record(
        receipt(
            1,
            signal="resource_availability",
            assessment_status="stop_observed",
        )
    )
    assert len(await state.read_states(FINDING_STATE_PREFIX, limit=100)) == 2
    assert (await current(state)).status == "active"


async def test_concurrent_replays_preserve_one_notification_revision() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await asyncio.gather(*(store.record(receipt()) for _ in range(10)))
    assert (await current(state)).notification_version == 1


async def test_legacy_receipt_remains_history_only() -> None:
    state = InMemoryStateStore()
    await AnalyzerFindingStateStore(state).record(receipt(severity=None))
    assert not await state.read_states(FINDING_STATE_PREFIX, limit=100)


async def test_evidence_gap_does_not_replace_a_fault_or_create_a_notification() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt())
    await store.record(
        receipt(1, assessment_status="insufficient_evidence", evidence_complete=False)
    )
    assert (await current(state)).revision == 1


async def test_recovery_cannot_close_a_changed_fault_revision() -> None:
    state = InMemoryStateStore()
    store = AnalyzerFindingStateStore(state)
    await store.record(receipt())
    prior = await current(state)
    await store.record(receipt(1))
    with pytest.raises(ValueError, match="prior revision"):
        await store.record(
            receipt(
                2,
                recovery_closed=True,
                recovery_finding_ref=prior.finding_id,
                recovery_prior_revision=prior.revision,
            )
        )
    assert (await current(state)).status == "active"


async def test_already_recovered_restart_remains_a_newly_observed_historical_finding() -> None:
    state = InMemoryStateStore()
    await AnalyzerFindingStateStore(state).record(
        receipt(
            signal="container_restart",
            resource_kind="kubernetes_pod",
            assessment_status="container_restart",
            recovery_closed=True,
        )
    )
    rows = await state.read_states(FINDING_STATE_PREFIX, limit=100)
    assert len(rows) == 1
    finding = FindingState.model_validate(rows[0])
    assert finding.status == "resolved"
    assert finding.notification_reason == "opened"
