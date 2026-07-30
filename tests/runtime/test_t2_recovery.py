from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.tiers.t2_reasoning import (
    BoundedFailoverT2Proposer,
    T2AttemptReceipt,
    T2FailureClass,
)
from fdai.runtime.t2_recovery import DurableT2RecoveryObserver, bind_t2_recovery_observer
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Ingress:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def ingest(self, raw: dict[str, object]) -> None:
        self.events.append(raw)


def _receipt(
    *,
    attempt: int = 1,
    status: str = "failed",
    terminal: bool = False,
    recovered: bool = False,
    failure_class: T2FailureClass | None = T2FailureClass.PROVIDER_ERROR,
) -> T2AttemptReceipt:
    return T2AttemptReceipt(
        event_id="event-1",
        correlation_id="correlation-1",
        route_ref="primary" if attempt == 1 else "secondary",
        attempt=attempt,
        candidate_count=2,
        status=status,
        failure_class=failure_class,
        retryable=True,
        terminal=terminal,
        recovered=recovered,
        observed_at=datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
    )


async def test_first_receipt_persists_atomically_then_enters_huginn() -> None:
    store = InMemoryStateStore()
    ingress = _Ingress()
    observer = DurableT2RecoveryObserver(store=store, ingress=ingress.ingest)

    await observer.observe(_receipt())

    records = await store.read_states("t2-recovery:receipt:", limit=10)
    assert len(records) == 1
    assert records[0]["failure_class"] == "provider_error"
    assert len(tuple(store.audit_entries)) == 2
    assert len(ingress.events) == 1
    event = ingress.events[0]
    assert event["event_type"] == "control_plane.t2_proposer_attempt"
    assert event["resource_id"] == "control-plane:t2-proposer"
    assert event["resource_type"] == "llm-endpoint"
    assert event["incident_correlation"] == "none"
    assert event["severity"] == "medium"
    event_text = str(event).casefold()
    assert "https://" not in event_text
    assert "secret" not in event_text


async def test_duplicate_receipt_does_not_duplicate_audit_or_event() -> None:
    store = InMemoryStateStore()
    ingress = _Ingress()
    observer = DurableT2RecoveryObserver(store=store, ingress=ingress.ingest)
    receipt = _receipt()

    await observer.observe(receipt)
    await observer.observe(receipt)

    assert len(tuple(store.audit_entries)) == 2
    assert len(ingress.events) == 1


async def test_terminal_failure_is_incident_correlated_high_severity() -> None:
    store = InMemoryStateStore()
    ingress = _Ingress()
    observer = DurableT2RecoveryObserver(store=store, ingress=ingress.ingest)

    await observer.observe(_receipt(attempt=2, terminal=True))

    event = ingress.events[0]
    assert event["incident_correlation"] == "correlate"
    assert event["severity"] == "high"
    assert event["attributes"] == {
        "route_ref": "secondary",
        "attempt": 2,
        "candidate_count": 2,
        "status": "failed",
        "failure_class": "provider_error",
        "retryable": True,
        "terminal": True,
        "recovered": False,
    }


async def test_recovery_success_remains_observable_without_opening_incident() -> None:
    store = InMemoryStateStore()
    ingress = _Ingress()
    observer = DurableT2RecoveryObserver(store=store, ingress=ingress.ingest)

    await observer.observe(
        _receipt(
            attempt=2,
            status="succeeded",
            terminal=True,
            recovered=True,
            failure_class=None,
        )
    )

    event = ingress.events[0]
    assert event["event_type"] == "control_plane.t2_proposer_recovered"
    assert event["incident_correlation"] == "none"
    assert event["severity"] == "info"


def test_binding_helper_binds_only_observable_proposers() -> None:
    store = InMemoryStateStore()
    ingress = _Ingress()

    class _Proposer:
        async def propose(self, **_kwargs: object) -> None:
            return None

    candidate = _Proposer()
    failover = BoundedFailoverT2Proposer(candidates=(("primary", candidate),))

    assert (
        bind_t2_recovery_observer(
            proposer=candidate,
            store=store,
            ingress=ingress.ingest,
        )
        is None
    )
    assert (
        bind_t2_recovery_observer(
            proposer=failover,
            store=store,
            ingress=ingress.ingest,
        )
        is not None
    )
