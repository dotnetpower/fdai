"""Runtime exemption lifecycle worker: idempotent digest delivery and fail-safe scheduling."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.notifications.router import (
    DeliveryMode,
    RouteOutcome,
    RouteSpec,
    RoutingResult,
)
from fdai.delivery.exemption_lifecycle import ExemptionLifecycleCoordinator
from fdai.rule_catalog.schema.exemption import Exemption, load_exemption_from_mapping
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionExpiryDigest,
    ExemptionExpiryDigestItem,
)
from fdai.runtime.exemption_lifecycle import (
    ExemptionLifecycleWorker,
    RouterExemptionLifecycleNotifier,
    build_digest_message,
    build_exemption_lifecycle_worker,
)
from fdai.shared.providers.notifications.base import NotificationMessage, TrustTier
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _exemption(exemption_id: str, expires_at: str) -> Exemption:
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


class _Router:
    def __init__(self, outcome: RouteOutcome = RouteOutcome.DELIVERED_ALL) -> None:
        self.outcome = outcome
        self.messages: list[NotificationMessage] = []

    async def dispatch(self, message: NotificationMessage) -> RoutingResult:
        self.messages.append(message)
        return RoutingResult(
            outcome=self.outcome,
            route=RouteSpec(
                category=message.category,
                trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
                delivery_mode=DeliveryMode.FANOUT,
                channels=("email-oncall",),
            ),
            attempted_channel_ids=("email-oncall",),
        )


def _worker(router: _Router, store: InMemoryStateStore, *exemptions: Exemption):
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=exemptions,
        notifier=RouterExemptionLifecycleNotifier(router),
        audit_store=store,
        alert_lead_days=14,
        clock=lambda: _NOW,
    )
    return ExemptionLifecycleWorker(coordinator, interval_seconds=1.0)


async def test_an_expiring_exemption_is_delivered_once_across_repeated_sweeps() -> None:
    router, store = _Router(), InMemoryStateStore()
    worker = _worker(router, store, _exemption("e.soon", "2026-08-25T00:00:00Z"))

    await worker.run_once()
    await worker.run_once()

    assert len(router.messages) == 1
    message = router.messages[0]
    assert message.trust_tier is TrustTier.A2_OPERATIONAL_ALERT
    assert message.audit_id and message.audit_id.startswith("exemption-expiry-digest:")
    assert "e.soon" in message.body_markdown
    actions = [entry["entry"]["action_kind"] for entry in store.audit_entries]
    assert "governance.exemption_alert" in actions


async def test_a_failed_delivery_is_retried_on_the_next_sweep_without_stopping_the_worker() -> None:
    router, store = _Router(RouteOutcome.FAILED_ALL), InMemoryStateStore()
    worker = _worker(router, store, _exemption("e.soon", "2026-08-25T00:00:00Z"))

    await worker.run_once()
    router.outcome = RouteOutcome.DELIVERED_ALL
    await worker.run_once()
    await worker.run_once()

    assert len(router.messages) == 2
    assert router.messages[0].audit_id == router.messages[1].audit_id


async def test_a_not_delivered_outcome_raises_from_the_notifier() -> None:
    notifier = RouterExemptionLifecycleNotifier(_Router(RouteOutcome.ESCALATED_TO_HIL))
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(_exemption("e.soon", "2026-08-25T00:00:00Z"),),
        notifier=notifier,
        audit_store=InMemoryStateStore(),
        alert_lead_days=14,
    )

    with pytest.raises(RuntimeError, match="not delivered"):
        await coordinator.run_once(now=_NOW)


async def test_the_sweep_publishes_no_expiry_command_and_only_audits_a_due_expiry() -> None:
    router, store = _Router(), InMemoryStateStore()
    worker = _worker(router, store, _exemption("e.late", "2026-08-10T00:00:00Z"))

    await worker.run_once()

    actions = {entry["entry"]["action_kind"] for entry in store.audit_entries}
    assert "governance.exemption_expiry_due" in actions
    assert "governance.exemption_expiry_held" in actions
    assert router.messages == []


def _digest(count: int, revision: str) -> ExemptionExpiryDigest:
    return ExemptionExpiryDigest(
        schema_version="1.0.0",
        generated_at=_NOW,
        items=tuple(
            ExemptionExpiryDigestItem(
                exemption_id=f"e{i:03d}",
                exemption_revision=revision,
                rule_id="rule-a",
                requested_by="requester",
                expires_at=_NOW + timedelta(days=1),
            )
            for i in range(count)
        ),
    )


def test_the_digest_message_is_bounded_and_stable_for_the_same_revisions() -> None:
    first = build_digest_message(_digest(25, "sha256:" + "a" * 64))

    assert first.body_markdown.count("\n- ") == 21
    assert "and 5 more" in first.body_markdown
    assert build_digest_message(_digest(25, "sha256:" + "a" * 64)).audit_id == first.audit_id
    assert build_digest_message(_digest(25, "sha256:" + "b" * 64)).audit_id != first.audit_id


async def test_run_stops_promptly_when_signalled() -> None:
    router, store = _Router(), InMemoryStateStore()
    worker = _worker(router, store, _exemption("e.soon", "2026-08-25T00:00:00Z"))
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.05)
    stop.set()

    await asyncio.wait_for(task, timeout=2.0)

    assert len(router.messages) == 1


def test_builder_is_absent_without_exemptions_or_when_disabled() -> None:
    exemption = _exemption("e.soon", "2026-08-25T00:00:00Z")

    def build(exemptions: tuple[Exemption, ...], environment: dict[str, str]):
        return build_exemption_lifecycle_worker(
            exemptions=exemptions,
            audit_store=InMemoryStateStore(),
            notification_router=_Router(),
            alert_lead_days=14,
            environment=environment,
        )

    assert build((), {}) is None
    assert build((exemption,), {"FDAI_EXEMPTION_LIFECYCLE_ENABLED": "false"}) is None
    assert build((exemption,), {}) is not None


def test_interval_is_bounded() -> None:
    coordinator = ExemptionLifecycleCoordinator(
        exemptions=(),
        notifier=RouterExemptionLifecycleNotifier(_Router()),
        audit_store=InMemoryStateStore(),
        alert_lead_days=14,
    )
    with pytest.raises(ValueError, match="interval"):
        ExemptionLifecycleWorker(coordinator, interval_seconds=0.5)
