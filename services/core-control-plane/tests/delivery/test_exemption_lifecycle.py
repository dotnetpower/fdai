"""ExemptionLifecycleCoordinator - idempotent alert + lifecycle audit evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.exemption_lifecycle import ExemptionLifecycleCoordinator
from fdai.rule_catalog.schema.exemption import Exemption, load_exemption_from_mapping
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _exemption(*, exemption_id: str, expires_at: str) -> Exemption:
    return load_exemption_from_mapping(
        {
            "schema_version": "1.0.0",
            "id": exemption_id,
            "rule_id": "rule-a",
            "scope": {
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-a",
            },
            "justification": "Waived while a migration is being completed for this scope.",
            "requested_by": "00000000-0000-0000-0000-000000000001",
            "approved_by": "00000000-0000-0000-0000-000000000002",
            "state": "active",
            "created_at": "2026-08-01T00:00:00Z",
            "expires_at": expires_at,
        }
    )


class _RecordingNotifier:
    def __init__(self) -> None:
        self.notified: list[str] = []

    async def notify_ahead_of_expiry(self, *, exemption: Exemption, decision: object) -> None:
        del decision
        self.notified.append(exemption.id)


class _FailOnceNotifier(_RecordingNotifier):
    async def notify_ahead_of_expiry(self, *, exemption: Exemption, decision: object) -> None:
        if not self.notified:
            self.notified.append("failed")
            raise RuntimeError("notification unavailable")
        await super().notify_ahead_of_expiry(exemption=exemption, decision=decision)


_NOW = datetime(2026, 8, 20, tzinfo=UTC)


@pytest.mark.asyncio
async def test_ahead_of_expiry_alert_notifies_and_audits() -> None:
    exemption = _exemption(exemption_id="e.soon", expires_at="2026-08-25T00:00:00Z")
    notifier = _RecordingNotifier()
    store = InMemoryStateStore()
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=notifier,
        audit_store=store,
        alert_lead_days=14,
    )

    result = await coordinator.run_once(now=_NOW)

    assert result.evaluated == 1
    assert result.alerted == 1
    assert notifier.notified == ["e.soon"]
    audit = list(store.audit_entries)
    assert any(entry["entry"]["action_kind"] == "governance.exemption_alert" for entry in audit)


@pytest.mark.asyncio
async def test_alert_is_delivered_at_most_once_across_runs() -> None:
    exemption = _exemption(exemption_id="e.soon", expires_at="2026-08-25T00:00:00Z")
    notifier = _RecordingNotifier()
    store = InMemoryStateStore()
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=notifier,
        audit_store=store,
        alert_lead_days=14,
    )

    first = await coordinator.run_once(now=_NOW)
    second = await coordinator.run_once(now=_NOW)

    assert first.alerted == 1
    assert second.alerted == 0
    assert notifier.notified == ["e.soon"]  # not called twice


@pytest.mark.asyncio
async def test_failed_alert_is_audited_and_retried_until_delivered() -> None:
    exemption = _exemption(exemption_id="e.soon", expires_at="2026-08-25T00:00:00Z")
    notifier = _FailOnceNotifier()
    store = InMemoryStateStore()
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=notifier,
        audit_store=store,
        alert_lead_days=14,
    )

    with pytest.raises(RuntimeError, match="notification unavailable"):
        await coordinator.run_once(now=_NOW)
    result = await coordinator.run_once(now=_NOW)

    assert result.alerted == 1
    assert notifier.notified == ["failed", "e.soon"]
    kinds = [record["entry"]["action_kind"] for record in store.audit_entries]
    assert kinds == [
        "governance.exemption_alert_attempted",
        "governance.exemption_alert_failed",
        "governance.exemption_alert_retried",
        "governance.exemption_alert",
    ]


@pytest.mark.asyncio
async def test_due_expiry_is_audited_without_notifying() -> None:
    exemption = _exemption(exemption_id="e.past", expires_at="2026-08-19T00:00:00Z")
    notifier = _RecordingNotifier()
    store = InMemoryStateStore()
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=notifier,
        audit_store=store,
        alert_lead_days=14,
    )

    result = await coordinator.run_once(now=_NOW)

    assert result.expired_due == 1
    assert result.alerted == 0
    assert notifier.notified == []
    audit = list(store.audit_entries)
    assert any(
        entry["entry"]["action_kind"] == "governance.exemption_expiry_due" for entry in audit
    )


@pytest.mark.asyncio
async def test_due_expiry_audit_is_recorded_once_across_runs() -> None:
    exemption = _exemption(exemption_id="e.past", expires_at="2026-08-19T00:00:00Z")
    store = InMemoryStateStore()
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=_RecordingNotifier(),
        audit_store=store,
        alert_lead_days=14,
    )

    first = await coordinator.run_once(now=_NOW)
    second = await coordinator.run_once(now=_NOW)

    assert first.expired_due == 1
    assert second.expired_due == 0
    due_entries = [
        record["entry"]
        for record in store.audit_entries
        if record["entry"]["action_kind"] == "governance.exemption_expiry_due"
    ]
    assert len(due_entries) == 1


@pytest.mark.asyncio
async def test_no_decision_evaluates_to_empty_result() -> None:
    exemption = _exemption(exemption_id="e.far", expires_at="2027-08-01T00:00:00Z")
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption,),
        notifier=_RecordingNotifier(),
        audit_store=InMemoryStateStore(),
        alert_lead_days=14,
    )

    result = await coordinator.run_once(now=_NOW)

    assert result == type(result)(evaluated=0, alerted=0, expired_due=0)
