"""Focused tests for the Executor-owned Event Hubs Kafka adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import fdai_executor_service.adapters.event_hubs_kafka as event_bus_module
import fdai_executor_service.cli as executor_cli
import pytest
from fdai_executor_service.adapters.event_hubs_kafka import (
    EventHubsKafkaBus,
    EventHubsKafkaBusConfig,
    _audience_from_bootstrap,
    _decode,
    _encode,
    _EntraTokenProvider,
    _iter_consumer,
)
from fdai_service_contracts.executor import IdentityToken


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="event-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _config() -> EventHubsKafkaBusConfig:
    return EventHubsKafkaBusConfig(
        bootstrap_servers="events.servicebus.windows.net:9093",
        auto_offset_reset="earliest",
    )


def test_event_bus_bounds_and_namespace_audience() -> None:
    assert (
        _audience_from_bootstrap("events.servicebus.windows.net:9093")
        == "https://events.servicebus.windows.net/.default"
    )
    with pytest.raises(ValueError, match="request_timeout_ms"):
        EventHubsKafkaBusConfig(
            bootstrap_servers="events.servicebus.windows.net:9093",
            request_timeout_ms=59_999,
        )
    with pytest.raises(ValueError, match="max_request_size"):
        EventHubsKafkaBusConfig(
            bootstrap_servers="events.servicebus.windows.net:9093",
            max_request_size=1_000_001,
        )


def test_executor_cli_composes_the_service_owned_kafka_config() -> None:
    assert executor_cli.EventHubsKafkaBusConfig is EventHubsKafkaBusConfig


async def test_entra_provider_uses_namespace_scoped_identity_token() -> None:
    identity = _Identity()
    provider = _EntraTokenProvider(identity, "https://events.example/.default")

    token = await provider.token()

    assert token == "event-token"
    assert provider.expires_at is not None
    assert identity.audiences == ["https://events.example/.default"]


async def test_publish_failure_discards_producer_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producers: list[_Producer] = []

    class _Producer:
        def __init__(self, **_kwargs: object) -> None:
            self.index = len(producers)
            self.stopped = False
            producers.append(self)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            self.stopped = True

        async def send_and_wait(self, topic: str, **_kwargs: object) -> object:
            if self.index == 0:
                raise RuntimeError("transport failed")
            return SimpleNamespace(topic=topic, partition=0, offset=7)

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _Producer)
    bus = EventHubsKafkaBus(identity=_Identity(), config=_config())

    with pytest.raises(RuntimeError, match="transport failed"):
        await bus.publish("executor.receipts", "one", {"status": "failed"})
    receipt = await bus.publish("executor.receipts", "two", {"status": "succeeded"})

    assert len(producers) == 2
    assert producers[0].stopped is True
    assert receipt.offset == 7


async def test_dead_letter_uses_sibling_topic_and_canonical_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    class _Producer:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send_and_wait(self, topic: str, **kwargs: object) -> object:
            sent["topic"] = topic
            sent.update(kwargs)
            return SimpleNamespace(topic=topic, partition=0, offset=1)

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _Producer)
    bus = EventHubsKafkaBus(identity=_Identity(), config=_config())

    await bus.dead_letter("executor.commands", "resource-one", {"bad": True}, "invalid")

    assert sent["topic"] == "executor.commands.dlq"
    assert json.loads(sent["value"]) == {
        "original_topic": "executor.commands",
        "payload": {"bad": True},
        "reason": "invalid",
    }


async def test_consumer_commits_only_after_caller_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumers: list[_Consumer] = []

    class _Consumer:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.provider = kwargs["sasl_oauth_token_provider"]
            self.commits = 0
            self.delivered = False
            consumers.append(self)

        async def start(self) -> None:
            await self.provider.token()

        async def stop(self) -> None:
            return None

        async def getone(self) -> object:
            if self.delivered:
                raise RuntimeError("consumer complete")
            self.delivered = True
            return SimpleNamespace(
                topic="executor.commands",
                key=b"resource-one",
                value=b'{"command_id":"one"}',
                offset=4,
            )

        async def commit(self) -> None:
            self.commits += 1

    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", _Consumer)
    iterator = _iter_consumer(
        topic="executor.commands",
        group_id="executor-group",
        config=_config(),
        identity=_Identity(),
        audience="https://events.servicebus.windows.net/.default",
    )

    envelope = await anext(iterator)
    assert envelope.offset == 4
    assert consumers[0].commits == 0
    with pytest.raises(RuntimeError, match="consumer complete"):
        await anext(iterator)
    assert consumers[0].commits == 1


def test_decode_redacts_invalid_payload_and_encoding_is_deterministic() -> None:
    assert _encode({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    decoded = _decode(b"secret-invalid-json", topic="executor.commands")
    assert decoded == {"_decode_error": True, "_raw_bytes": 19}
    assert "secret-invalid-json" not in str(decoded)
