"""Process-loss, breaker, and supervision tests for channel delivery work."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    ChannelKind,
    channel_response_digest,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
    ChannelDeliveryWorkerConfig,
)

_NOW = datetime(2026, 8, 19, 22, 0, tzinfo=UTC)


def _record(kind: ChannelKind, suffix: str) -> ChannelDeliveryRecord:
    response = {
        "status": "answered",
        "answer": "Verified answer",
        "verification": {"authority": "ontology-query", "evidence_refs": []},
    }
    return ChannelDeliveryRecord(
        delivery_id=f"delivery-{suffix}",
        idempotency_key=f"idempotency-{suffix}",
        principal_id="principal-example",
        scope_ref="scope://example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        channel_kind=kind,
        response=response,
        response_digest=channel_response_digest(response),
        state=ChannelDeliveryState.SENDING,
        created_at=_NOW,
        due_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
        retention_until=_NOW + timedelta(days=1),
        attempt_count=1,
        lease_owner="operator-channel-edge",
        lease_expires_at=_NOW + timedelta(seconds=30),
    )


class _Store:
    def __init__(self) -> None:
        self.breakers: dict[str, ChannelAdapterBreaker] = {}
        self.due: dict[ChannelKind, list[ChannelDeliveryRecord]] = {}
        self.reconciled = 2
        self.claimed_channels: list[ChannelKind] = []

    async def reconcile_sending(self, *, now: datetime) -> int:
        del now
        return self.reconciled

    async def claim_due(self, *, channel_kind: ChannelKind | None = None, **_kwargs: object):  # type: ignore[no-untyped-def]
        assert channel_kind is not None
        self.claimed_channels.append(channel_kind)
        return tuple(self.due.pop(channel_kind, []))

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None:
        return self.breakers.get(adapter_id)

    async def put_breaker(
        self,
        record: ChannelAdapterBreaker,
        *,
        expected_revision: int | None,
    ) -> ChannelAdapterBreaker:
        current = self.breakers.get(record.adapter_id)
        if expected_revision is None:
            if current is not None:
                raise ValueError("exists")
        elif current is None or current.revision != expected_revision:
            raise ValueError("compare-and-set")
        self.breakers[record.adapter_id] = record
        return record


class _Handler:
    def __init__(self, state: ChannelDeliveryState) -> None:
        self.state = state
        self.records: list[ChannelDeliveryRecord] = []

    async def deliver_claimed(self, record: ChannelDeliveryRecord) -> ChannelDeliveryRecord:
        self.records.append(record)
        return replace(
            record,
            state=self.state,
            lease_owner=None,
            lease_expires_at=None,
            duplicate_risk=self.state is ChannelDeliveryState.AMBIGUOUS,
            terminal_at=_NOW if self.state.immutable else None,
        )


async def test_initialize_reconciles_before_ready_and_creates_breakers() -> None:
    store = _Store()
    worker = ChannelDeliveryWorker(store=store, handler=_Handler(ChannelDeliveryState.DELIVERED))  # type: ignore[arg-type]

    assert worker.ready is False
    assert await worker.initialize() == 2
    assert set(store.breakers) == {
        "operator-channel-edge:slack",
        "operator-channel-edge:teams",
    }


async def test_run_once_skips_open_breaker_before_claim() -> None:
    store = _Store()
    handler = _Handler(ChannelDeliveryState.DELIVERED)
    worker = ChannelDeliveryWorker(store=store, handler=handler)  # type: ignore[arg-type]
    await worker.initialize()
    store.breakers["operator-channel-edge:teams"] = replace(
        store.breakers["operator-channel-edge:teams"],
        mode=ChannelBreakerMode.OPEN,
        revision=1,
        reason="manual pause",
    )
    store.due[ChannelKind.SLACK] = [_record(ChannelKind.SLACK, "slack")]
    store.due[ChannelKind.TEAMS] = [_record(ChannelKind.TEAMS, "teams")]

    assert await worker.run_once() == 1
    assert store.claimed_channels == [ChannelKind.SLACK]
    assert [record.channel_kind for record in handler.records] == [ChannelKind.SLACK]


async def test_failure_threshold_opens_breaker_and_stops_batch() -> None:
    store = _Store()
    handler = _Handler(ChannelDeliveryState.AMBIGUOUS)
    worker = ChannelDeliveryWorker(  # type: ignore[arg-type]
        store=store,
        handler=handler,
        config=ChannelDeliveryWorkerConfig(
            channels=(ChannelKind.SLACK,),
            failure_threshold=1,
        ),
        clock=lambda: _NOW,
    )
    await worker.initialize()
    store.due[ChannelKind.SLACK] = [
        _record(ChannelKind.SLACK, "one"),
        _record(ChannelKind.SLACK, "two"),
    ]

    assert await worker.run_once() == 1
    assert store.breakers["operator-channel-edge:slack"].mode is ChannelBreakerMode.OPEN
    assert len(handler.records) == 1


async def test_start_and_close_leave_no_ready_task() -> None:
    worker = ChannelDeliveryWorker(
        store=_Store(),  # type: ignore[arg-type]
        handler=_Handler(ChannelDeliveryState.DELIVERED),
        config=ChannelDeliveryWorkerConfig(idle_seconds=60),
    )

    await worker.start()
    assert worker.ready is True
    await worker.close()
    assert worker.ready is False
