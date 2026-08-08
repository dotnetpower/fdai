"""StateStoreHilEscalationSink - persist a router escalation (fail-safe queue)."""

from __future__ import annotations

from fdai.delivery.notifications import StateStoreHilEscalationSink
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _msg(
    *, category: str = "operational_alert", correlation_id: str = "corr-1"
) -> NotificationMessage:
    return NotificationMessage(
        category=category,
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=correlation_id,
        title="Adapter degraded",
        body_markdown="Every ops channel failed for this alert.",
        severity=Severity.ERROR,
        audit_id="audit-1",
    )


async def test_escalate_parks_record_and_audits() -> None:
    store = InMemoryStateStore()
    sink = StateStoreHilEscalationSink(state_store=store)

    await sink.escalate(_msg(), reason="all_channels_failed")

    parked = await store.read_state("notify_escalation:operational_alert:corr-1")
    assert parked is not None
    assert parked["category"] == "operational_alert"
    assert parked["trust_tier"] == "a2_operational_alert"
    assert parked["severity"] == "error"
    assert parked["reason"] == "all_channels_failed"
    assert parked["correlation_id"] == "corr-1"

    audit = store._audit  # noqa: SLF001 - assert the escalation was audited
    assert len(audit) == 1
    entry = audit[0]["entry"]
    assert entry["kind"] == "notification.escalation"
    assert entry["reason"] == "all_channels_failed"
    assert entry["correlation_id"] == "corr-1"


async def test_escalate_is_idempotent_by_category_and_correlation() -> None:
    """A retried escalation of the same message replaces the parked
    record rather than duplicating state (at-least-once safe)."""
    store = InMemoryStateStore()
    sink = StateStoreHilEscalationSink(state_store=store)

    await sink.escalate(_msg(), reason="first")
    await sink.escalate(_msg(), reason="second")

    parked = await store.read_state("notify_escalation:operational_alert:corr-1")
    assert parked is not None
    # Same key -> latest value wins, one parked record.
    assert parked["reason"] == "second"
    keys = [k for k in store._state if k.startswith("notify_escalation:")]  # noqa: SLF001
    assert keys == ["notify_escalation:operational_alert:corr-1"]


async def test_distinct_category_or_correlation_parks_separately() -> None:
    store = InMemoryStateStore()
    sink = StateStoreHilEscalationSink(state_store=store)

    await sink.escalate(_msg(category="operational_alert", correlation_id="corr-1"), reason="a")
    await sink.escalate(_msg(category="kill_switch_state", correlation_id="corr-1"), reason="b")
    await sink.escalate(_msg(category="operational_alert", correlation_id="corr-2"), reason="c")

    keys = sorted(k for k in store._state if k.startswith("notify_escalation:"))  # noqa: SLF001
    assert keys == [
        "notify_escalation:kill_switch_state:corr-1",
        "notify_escalation:operational_alert:corr-1",
        "notify_escalation:operational_alert:corr-2",
    ]


def test_custom_actor_is_recorded() -> None:
    sink = StateStoreHilEscalationSink(state_store=InMemoryStateStore(), actor="fork.sink")
    assert sink._actor == "fork.sink"  # noqa: SLF001
