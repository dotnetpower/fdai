"""Focused tests for the Operator-owned semantic Event Hubs Kafka adapter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import fdai_operator_service.adapters.semantic_kafka as kafka_module
from fdai_operator_service.adapters.semantic_kafka import (
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)


class Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.closed = 0

    async def get_token(self, scope: str) -> object:
        self.scopes.append(scope)
        return SimpleNamespace(token="redacted-token", expires_on=4_000_000_000)

    async def close(self) -> None:
        self.closed += 1


class Producer:
    latest: Producer | None = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.started = 0
        self.stopped = 0
        Producer.latest = self

    async def start(self) -> None:
        self.started += 1
        provider = self.kwargs["sasl_oauth_token_provider"]
        await provider.token()  # type: ignore[attr-defined]

    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> object:
        self.sent.append((topic, key, value))
        return object()

    async def stop(self) -> None:
        self.stopped += 1


class FailingProducer(Producer):
    async def start(self) -> None:
        self.started += 1
        raise ConnectionError("broker unavailable")


class Consumer:
    latest: Consumer | None = None
    messages: list[object] = []

    def __init__(self, topic: str, **kwargs: object) -> None:
        self.topic = topic
        self.kwargs = kwargs
        self.commits = 0
        self.started = 0
        self.stopped = 0
        self.waiting = asyncio.Event()
        self._messages = list(self.messages)
        Consumer.latest = self

    async def start(self) -> None:
        self.started += 1
        provider = self.kwargs["sasl_oauth_token_provider"]
        await provider.token()  # type: ignore[attr-defined]

    async def getone(self) -> object:
        if self._messages:
            return self._messages.pop(0)
        self.waiting.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def commit(self) -> None:
        self.commits += 1

    async def stop(self) -> None:
        self.stopped += 1


def _bus(monkeypatch) -> tuple[OperatorSemanticKafkaBus, Credential]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(kafka_module, "AIOKafkaProducer", Producer)
    monkeypatch.setattr(kafka_module, "AIOKafkaConsumer", Consumer)
    credential = Credential()
    return (
        OperatorSemanticKafkaBus(
            config=OperatorSemanticKafkaConfig(
                bootstrap_servers="example.servicebus.windows.net:9093"
            ),
            credential=credential,  # type: ignore[arg-type]
        ),
        credential,
    )


async def test_producer_uses_managed_identity_and_idempotent_sasl_ssl(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bus, credential = _bus(monkeypatch)

    await bus.publish("operator-core-request", "request-1", {"b": 2, "a": 1})
    await bus.aclose()

    producer = Producer.latest
    assert producer is not None
    assert producer.kwargs["security_protocol"] == "SASL_SSL"
    assert producer.kwargs["sasl_mechanism"] == "OAUTHBEARER"
    assert producer.kwargs["enable_idempotence"] is True
    assert producer.kwargs["acks"] == "all"
    assert producer.sent == [("operator-core-request", b"request-1", b'{"a":1,"b":2}')]
    assert credential.scopes == ["https://example.servicebus.windows.net/.default"]
    assert credential.closed == 1
    assert producer.stopped == 1


async def test_readiness_is_credential_free_and_live_probe_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bus, credential = _bus(monkeypatch)
    monkeypatch.setattr(kafka_module, "AIOKafkaProducer", FailingProducer)

    assert bus.readiness() is True
    assert credential.scopes == []
    assert await bus.probe_readiness() is False
    assert credential.scopes == []
    producer = Producer.latest
    assert producer is not None
    assert producer.stopped == 1
    await bus.aclose()


async def test_consumer_commits_only_after_yielded_payload_is_processed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    Consumer.messages = [
        SimpleNamespace(
            topic="core-operator-projection",
            key=b"request-1",
            value=b'{"status":"answer"}',
            offset=4,
        )
    ]
    bus, _ = _bus(monkeypatch)
    stream = bus.subscribe("core-operator-projection", "operator-semantic-turn-v1")

    assert await anext(stream) == {"status": "answer"}
    consumer = Consumer.latest
    assert consumer is not None
    assert consumer.commits == 0

    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(consumer.waiting.wait(), timeout=1)
    assert consumer.commits == 1
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    await stream.aclose()
    await bus.aclose()

    assert consumer.stopped == 1


async def test_invalid_payload_is_dead_lettered_and_committed_before_next_yield(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    Consumer.messages = [
        SimpleNamespace(
            topic="core-operator-projection",
            key=b"request-1",
            value=b"{",
            offset=7,
        ),
        SimpleNamespace(
            topic="core-operator-projection",
            key=b"request-2",
            value=b'{"status":"held"}',
            offset=8,
        ),
    ]
    bus, _ = _bus(monkeypatch)
    stream = bus.subscribe("core-operator-projection", "operator-semantic-turn-v1")

    assert await anext(stream) == {"status": "held"}
    consumer = Consumer.latest
    producer = Producer.latest
    assert consumer is not None
    assert producer is not None
    assert consumer.commits == 1
    assert producer.sent[0][0] == "core-operator-projection.dlq"
    assert producer.sent[0][1] == b"request-1"
    assert producer.sent[0][2] == (
        b'{"original_topic":"core-operator-projection",'
        b'"reason":"invalid_event_payload","source_offset":7}'
    )

    await stream.aclose()
    await bus.aclose()
