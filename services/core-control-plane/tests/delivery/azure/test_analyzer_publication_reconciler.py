"""Broker reconciliation never turns an incomplete scan into retry permission."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import pytest
from aiokafka import TopicPartition
from fdai.delivery.analyzer_tick import ANALYZER_EVENT_SOURCE
from fdai.delivery.azure import analyzer_publication_reconciler as module
from fdai.delivery.azure.event_bus import EventHubsKafkaBusConfig

EVENT_ID = UUID("00000000-0000-0000-0000-000000000011")
TOPIC = "fdai.observability.events"


@dataclass(frozen=True)
class Record:
    offset: int
    value: bytes


class Broker:
    def __init__(self, records: list[Record], *, beginning: int = 0, fail: bool = False) -> None:
        self.records = records
        self.beginning = beginning
        self.fail = fail
        self.position = beginning
        self.stopped = False
        self.group_id: object = object()
        self.auto_commit = True
        self.assigned: list[TopicPartition] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True

    async def partitions_for_topic(self, topic: str) -> set[int]:
        assert topic == TOPIC
        return {0}

    def assign(self, assigned: list[TopicPartition]) -> None:
        self.assigned = assigned

    async def beginning_offsets(self, assigned: list[TopicPartition]) -> dict[TopicPartition, int]:
        return {assigned[0]: self.beginning}

    async def end_offsets(self, assigned: list[TopicPartition]) -> dict[TopicPartition, int]:
        return {assigned[0]: max(self.beginning, len(self.records))}

    def seek(self, partition: TopicPartition, offset: int) -> None:
        assert partition == self.assigned[0]
        self.position = offset

    async def getmany(self, **kwargs: object) -> dict[TopicPartition, list[Record]]:
        if self.fail:
            raise RuntimeError("broker read failed")
        records = [row for row in self.records if row.offset >= self.position][:2]
        if records:
            self.position = records[-1].offset + 1
        return {self.assigned[0]: records}


def _record(
    event_id: UUID, key: str, *, offset: int = 0, source: str = ANALYZER_EVENT_SOURCE
) -> Record:
    return Record(
        offset=offset,
        value=json.dumps(
            {"event_id": str(event_id), "idempotency_key": key, "source": source}
        ).encode(),
    )


def _lookup(
    monkeypatch: pytest.MonkeyPatch, broker: Broker
) -> module.KafkaAnalyzerPublicationReconciler:
    def factory(**kwargs: object) -> Broker:
        broker.group_id = kwargs["group_id"]
        broker.auto_commit = kwargs["enable_auto_commit"]  # type: ignore[assignment]
        return broker

    monkeypatch.setattr(module, "AIOKafkaConsumer", factory)
    return module.KafkaAnalyzerPublicationReconciler(
        config=EventHubsKafkaBusConfig(
            bootstrap_servers="localhost:9092", security_protocol="PLAINTEXT"
        ),
        identity=None,
    )


@pytest.mark.asyncio
async def test_acceptance_survives_a_new_reader_and_does_not_consume_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = Broker([_record(UUID(int=3), "other"), _record(EVENT_ID, "key", offset=1)])
    reconciler = _lookup(monkeypatch, broker)

    receipt = await reconciler.reconcile(event_id=EVENT_ID, idempotency_key="key", topic=TOPIC)

    assert (receipt.topic, receipt.partition, receipt.offset) == (TOPIC, 0, 1)
    assert broker.group_id is None
    assert broker.auto_commit is False
    assert broker.stopped
    assert broker.position == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broker", "message"),
    [
        (Broker([_record(UUID(int=3), "other")]), "absence cannot be established"),
        (Broker([_record(EVENT_ID, "wrong")]), "identity conflicts"),
        (Broker([_record(EVENT_ID, "key", source="another.publisher")]), "identity conflicts"),
        (Broker([_record(EVENT_ID, "key")], fail=True), "broker read failed"),
        (Broker([_record(UUID(int=3), "other")], beginning=1), "absence cannot be established"),
    ],
)
async def test_inconclusive_or_conflicting_lookup_fails_closed(
    monkeypatch: pytest.MonkeyPatch, broker: Broker, message: str
) -> None:
    reconciler = _lookup(monkeypatch, broker)

    with pytest.raises(RuntimeError, match=message):
        await reconciler.reconcile(event_id=EVENT_ID, idempotency_key="key", topic=TOPIC)
    assert broker.stopped


@pytest.mark.asyncio
async def test_scan_limit_cannot_prove_an_older_record_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_MAX_RECORDS", 1)
    broker = Broker([_record(EVENT_ID, "key"), _record(UUID(int=3), "other", offset=1)])
    reconciler = _lookup(monkeypatch, broker)

    with pytest.raises(RuntimeError, match="absence cannot be established"):
        await reconciler.reconcile(event_id=EVENT_ID, idempotency_key="key", topic=TOPIC)
    assert broker.stopped
