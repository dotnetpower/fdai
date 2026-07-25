"""EventHubsKafkaBus - construction + close guards.

Full round-trip against Event Hubs requires a live broker (or an
aiokafka-compatible mock like ``redpanda`` in dev-up.sh); those cases
are covered by the persistence-style integration flow. The tests here
exercise the wire-adapter code paths that do not need a broker:

- construction guards on config values,
- the encoder/decoder helpers used by every message,
- token-provider bridging into aiokafka's async contract,
- ``close()`` idempotency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import fdai.delivery.azure.event_bus as event_bus_module
from fdai.delivery.azure.event_bus import (
    EventHubsKafkaBus,
    EventHubsKafkaBusConfig,
    _decode,  # type: ignore[attr-defined]
    _decode_key,  # type: ignore[attr-defined]
    _encode,  # type: ignore[attr-defined]
    _EntraTokenProvider,  # type: ignore[attr-defined]
    _iter_consumer,  # type: ignore[attr-defined]
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "fake-token") -> None:  # noqa: S107 - synthetic test fixture
        self._token = token
        self.calls: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.calls.append(audience)
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _cfg(**overrides: object) -> EventHubsKafkaBusConfig:
    base: dict[str, object] = {"bootstrap_servers": "evhns.servicebus.windows.net:9093"}
    base.update(overrides)
    return EventHubsKafkaBusConfig(**base)  # type: ignore[arg-type]


def test_construction_rejects_empty_bootstrap_servers() -> None:
    with pytest.raises(ValueError, match="bootstrap_servers"):
        EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg(bootstrap_servers=""))


def test_config_rejects_invalid_auto_offset_reset() -> None:
    with pytest.raises(ValueError, match="auto_offset_reset"):
        _cfg(auto_offset_reset="middle")


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"session_timeout_ms": 0}, "session_timeout_ms"),
        ({"heartbeat_interval_ms": 0}, "heartbeat_interval_ms"),
        (
            {"session_timeout_ms": 10_000, "heartbeat_interval_ms": 10_000},
            "less than session_timeout_ms",
        ),
        ({"dlq_suffix": ""}, "dlq_suffix"),
        ({"connections_max_idle_ms": 0}, "connections_max_idle_ms"),
        ({"connections_max_idle_ms": 240_000}, "connections_max_idle_ms"),
        ({"metadata_max_age_ms": 0}, "metadata_max_age_ms"),
        ({"metadata_max_age_ms": 240_000}, "metadata_max_age_ms"),
    ),
)
def test_config_rejects_unsafe_transport_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _cfg(**overrides)


def test_config_defaults_stay_below_event_hubs_idle_close_window() -> None:
    config = _cfg()

    assert config.connections_max_idle_ms == 180_000
    assert config.metadata_max_age_ms == 180_000


def test_encode_produces_deterministic_bytes() -> None:
    payload = {"b": 2, "a": 1}
    encoded = _encode(payload)
    assert encoded == b'{"a":1,"b":2}'
    # And matches after a round-trip through json.
    assert json.loads(encoded) == {"a": 1, "b": 2}


def test_decode_returns_empty_dict_for_none() -> None:
    assert _decode(None) == {}


def test_decode_wraps_non_dict_payload() -> None:
    result = _decode(b'"just-a-string"')
    assert result["_wrapped"] == "just-a-string"
    # A non-object payload is a poison message: mark it so downstream
    # can filter without re-parsing.
    assert result.get("_decode_error") is True


def test_decode_raw_fallback_on_bad_json() -> None:
    result = _decode(b"not-json{")
    assert "_raw" in result
    # Invalid JSON MUST carry the decode-error sentinel so downstream
    # ``payload.get("resource")`` lookups do not silently succeed against
    # a malformed message.
    assert result.get("_decode_error") is True


def test_decode_key_utf8() -> None:
    assert _decode_key(b"resource:example/rg/x") == "resource:example/rg/x"
    assert _decode_key(None) == ""


@pytest.mark.asyncio
async def test_entra_token_provider_delegates_to_workload_identity() -> None:
    identity = _StaticIdentity(token="entra-token-abc")
    provider = _EntraTokenProvider(identity, "https://evhns-test.servicebus.windows.net/.default")
    token = await provider.token()
    assert token == "entra-token-abc"
    # Namespace-scoped audience - Event Hubs rejects a generic
    # `https://eventhubs.azure.net` aud with `Invalid tenant name`.
    assert identity.calls == ["https://evhns-test.servicebus.windows.net/.default"]


def test_audience_defaults_to_namespace_fqdn() -> None:
    """The default audience MUST be derived from the bootstrap host."""
    from fdai.delivery.azure.event_bus import (  # type: ignore[attr-defined]
        _audience_from_bootstrap,
    )

    assert (
        _audience_from_bootstrap("evhns-test.servicebus.windows.net:9093")
        == "https://evhns-test.servicebus.windows.net/.default"
    )
    # Multi-host bootstrap: take the first entry.
    assert (
        _audience_from_bootstrap(
            "evhns-a.servicebus.windows.net:9093,evhns-b.servicebus.windows.net:9093"
        )
        == "https://evhns-a.servicebus.windows.net/.default"
    )


def test_audience_from_bootstrap_rejects_empty() -> None:
    from fdai.delivery.azure.event_bus import (  # type: ignore[attr-defined]
        _audience_from_bootstrap,
    )

    with pytest.raises(ValueError, match="audience"):
        _audience_from_bootstrap(":9093")


def test_config_audience_override_wins() -> None:
    """A caller MAY pin the audience for non-Azure Kafka endpoints."""
    override = "https://custom-broker.example/.default"
    bus = EventHubsKafkaBus(
        identity=_StaticIdentity(),
        config=_cfg(audience=override),
    )
    # Access via the private attribute so the invariant is enforced at
    # construction; production code never touches `_audience` directly.
    assert bus._audience == override  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_close_is_idempotent_before_start() -> None:
    bus = EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg())
    # Never started a producer - close MUST not raise.
    await bus.close()
    await bus.close()


@pytest.mark.asyncio
async def test_producer_start_failure_stops_partial_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[_StartFailingProducer] = []

    class _StartFailingProducer:
        def __init__(self, **_kwargs: object) -> None:
            self.stopped = False
            instances.append(self)

        async def start(self) -> None:
            raise RuntimeError("broker unavailable")

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _StartFailingProducer)
    bus = EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg())

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await bus.publish("aw.control.events", "event-1", {"event_id": "event-1"})

    assert len(instances) == 1
    assert instances[0].stopped is True
    assert vars(bus)["_producer"] is None


@pytest.mark.asyncio
async def test_publish_failure_discards_cached_producer_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[_RecoveringProducer] = []

    class _RecoveringProducer:
        def __init__(self, **_kwargs: object) -> None:
            self.index = len(instances)
            self.stopped = False
            instances.append(self)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            self.stopped = True

        async def send_and_wait(self, topic: str, **_kwargs: object) -> object:
            if self.index == 0:
                raise RuntimeError("producer transport failed")
            return SimpleNamespace(topic=topic, partition=1, offset=9)

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _RecoveringProducer)
    bus = EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg())

    with pytest.raises(RuntimeError, match="producer transport failed"):
        await bus.publish("aw.control.events", "event-1", {"event_id": "event-1"})

    receipt = await bus.publish("aw.control.events", "event-2", {"event_id": "event-2"})
    assert len(instances) == 2
    assert instances[0].stopped is True
    assert receipt.partition == 1
    assert receipt.offset == 9


@pytest.mark.asyncio
async def test_producer_receives_event_hubs_safe_connection_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _RecordingProducer:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _RecordingProducer)
    bus = EventHubsKafkaBus(identity=_StaticIdentity(), config=_cfg())

    await bus._get_producer()  # type: ignore[attr-defined]

    assert captured["connections_max_idle_ms"] == 180_000
    assert captured["metadata_max_age_ms"] == 180_000


@pytest.mark.asyncio
async def test_consumer_receives_event_hubs_safe_connection_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _RecordingConsumer:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        def __aiter__(self) -> _RecordingConsumer:
            return self

        async def __anext__(self) -> object:
            raise StopAsyncIteration

    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", _RecordingConsumer)
    iterator = _iter_consumer(
        topic="aw.control.canary",
        group_id="fdai-canary",
        config=_cfg(),
        identity=_StaticIdentity(),
        audience="https://evhns.servicebus.windows.net/.default",
    )

    with pytest.raises(StopAsyncIteration):
        await anext(iterator)

    assert captured["connections_max_idle_ms"] == 180_000
    assert captured["metadata_max_age_ms"] == 180_000


@pytest.mark.asyncio
async def test_consumer_start_failure_stops_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    instances: list[_StartFailingConsumer] = []

    class _StartFailingConsumer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.stopped = False
            instances.append(self)

        async def start(self) -> None:
            raise RuntimeError("topic unavailable")

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", _StartFailingConsumer)
    iterator = _iter_consumer(
        topic="aw.control.canary",
        group_id="fdai-canary",
        config=_cfg(),
        identity=_StaticIdentity(),
        audience="https://evhns.servicebus.windows.net/.default",
    )

    with pytest.raises(RuntimeError, match="topic unavailable"):
        await anext(iterator)

    assert len(instances) == 1
    assert instances[0].stopped is True
