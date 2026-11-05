"""Focused tests for the Executor-owned Event Hubs Kafka adapter."""

from __future__ import annotations

import asyncio
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
)
from fdai_executor_service.runtime import IsolatedExecutorCommandConsumer
from fdai_service_contracts.executor import IdentityToken

_FIXED_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="event-token",
            expires_at=_FIXED_NOW + timedelta(hours=1),
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


async def test_plaintext_transport_needs_no_workload_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Producer:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _Producer)
    bus = EventHubsKafkaBus(
        identity=None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers="127.0.0.1:19092",
            security_protocol="PLAINTEXT",
        ),
    )

    await bus.assert_publish_ready()

    assert captured["security_protocol"] == "PLAINTEXT"
    assert "sasl_mechanism" not in captured
    assert "sasl_oauth_token_provider" not in captured


def test_local_executor_config_is_shadow_only_without_managed_identity() -> None:
    environment = {
        "RUNTIME_ENV": "dev",
        "FDAI_EXECUTION_VENUE": "local",
        "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT": "8013",
    }

    config = executor_cli.IsolatedExecutorRuntimeConfig.from_env(environment)

    assert config.execution_venue == "local"
    assert config.authority_cutover is False
    assert config.health_port == 8013


def test_local_executor_rejects_authority_cutover() -> None:
    environment = {
        "RUNTIME_ENV": "dev",
        "FDAI_EXECUTION_VENUE": "local",
        "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
    }

    with pytest.raises(RuntimeError, match="MUST NOT enable authority cutover"):
        executor_cli.IsolatedExecutorRuntimeConfig.from_env(environment)


def test_legacy_unbound_transition_requires_authority_cutover() -> None:
    environment = {
        "RUNTIME_ENV": "dev",
        "FDAI_EXECUTION_VENUE": "local",
        "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_LEGACY_UNBOUND_TRANSITION": "1",
    }

    with pytest.raises(RuntimeError, match="requires authority cutover"):
        executor_cli.IsolatedExecutorRuntimeConfig.from_env(environment)


def test_deployed_kubernetes_cutover_does_not_require_azure_effect_identities() -> None:
    environment = {
        "RUNTIME_ENV": "prod",
        "FDAI_EXECUTION_VENUE": "deployed",
        "KAFKA_BOOTSTRAP_SERVERS": "events.example.invalid:9093",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": ("00000000-0000-0000-0000-000000000001"),
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        "FDAI_KUBERNETES_DIRECT_API_JSON": "{}",
    }

    config = executor_cli.IsolatedExecutorRuntimeConfig.from_env(environment)

    assert config.authority_cutover is True


def test_deployed_cutover_rejects_missing_effect_adapter() -> None:
    environment = {
        "RUNTIME_ENV": "prod",
        "FDAI_EXECUTION_VENUE": "deployed",
        "KAFKA_BOOTSTRAP_SERVERS": "events.example.invalid:9093",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_executor",
        "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": ("00000000-0000-0000-0000-000000000001"),
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
    }

    with pytest.raises(RuntimeError, match="requires a direct-API adapter"):
        executor_cli.IsolatedExecutorRuntimeConfig.from_env(environment)


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


async def test_receipt_producer_readiness_requires_initialized_live_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Producer:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _Producer)
    bus = EventHubsKafkaBus(identity=_Identity(), config=_config())

    assert bus.producer_ready is False
    await bus.assert_publish_ready()
    assert bus.producer_ready is True
    await bus.close()
    assert bus.producer_ready is False


async def test_executor_readiness_rejects_stale_receipt_outbox_state() -> None:
    now = 10.0
    claims = 0
    available = True

    class _Bus:
        def subscribe(self, _topic: str, _group_id: str) -> object:
            async def events() -> object:
                await asyncio.Event().wait()
                yield None

            return events()

    class _Outbox:
        async def claim_receipts(self, *, limit: int) -> tuple[()]:
            nonlocal claims
            assert limit == 100
            claims += 1
            if not available:
                raise RuntimeError("receipt state unavailable")
            return ()

        async def commit_receipt(self, *_args: object) -> None:
            return None

        async def mark_receipt_published(self, _receipt_id: object) -> None:
            return None

    consumer = IsolatedExecutorCommandConsumer(
        event_bus=_Bus(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
        retry_seconds=0.001,
        receipt_outbox=_Outbox(),  # type: ignore[arg-type]
        outbox_readiness_freshness_seconds=0.01,
        monotonic=lambda: now,
    )
    running = asyncio.create_task(consumer.run())
    while claims == 0:
        await asyncio.sleep(0)
    assert consumer.receipt_publication_ready

    available = False
    now = 10.02
    while claims < 2:
        await asyncio.sleep(0)
    assert not consumer.receipt_publication_ready
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)


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
    bus = EventHubsKafkaBus(identity=_Identity(), config=_config())
    iterator = bus.subscribe("executor.commands", "executor-group")

    assert bus.consumer_ready is False
    envelope = await anext(iterator)
    assert envelope.offset == 4
    assert bus.consumer_ready is True
    assert consumers[0].commits == 0
    with pytest.raises(RuntimeError, match="consumer complete"):
        await anext(iterator)
    assert consumers[0].commits == 1
    assert bus.consumer_ready is False


def test_decode_redacts_invalid_payload_and_encoding_is_deterministic() -> None:
    assert _encode({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    decoded = _decode(b"secret-invalid-json", topic="executor.commands")
    assert decoded == {"_decode_error": True, "_raw_bytes": 19}
    assert "secret-invalid-json" not in str(decoded)
    assert _decode(None, topic="executor.commands") == {}
    assert _decode(b"[1, 2]", topic="executor.commands") == {
        "_decode_error": True,
        "_payload_type": "list",
    }


async def test_event_bus_config_and_transport_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_executor_service.adapters.event_hubs_kafka import (
        _iter_consumer,
        _stop_after_failure,
        _stop_consumer,
        _token_refresh_delay,
        _transport_options,
    )

    with pytest.raises(ValueError, match="cannot derive Event Hubs audience"):
        _audience_from_bootstrap(":9093")

    for kwargs, match in [
        ({"bootstrap_servers": ""}, "bootstrap_servers MUST NOT be empty"),
        ({"security_protocol": "SSL"}, "security_protocol MUST be"),
        ({"auto_offset_reset": "none"}, "auto_offset_reset MUST be"),
        ({"session_timeout_ms": 0}, "session_timeout_ms MUST be positive"),
        ({"heartbeat_interval_ms": 0}, "heartbeat_interval_ms MUST be positive"),
        ({"dlq_suffix": ""}, "dlq_suffix MUST NOT be empty"),
        ({"connections_max_idle_ms": 240_000}, "connections_max_idle_ms MUST be below"),
        ({"metadata_max_age_ms": 240_000}, "metadata_max_age_ms MUST be below"),
        ({"retry_backoff_ms": 500}, "retry_backoff_ms MUST be at least"),
        ({"token_refresh_margin_seconds": 0}, "token_refresh_margin_seconds MUST be positive"),
        ({"token_refresh_jitter_seconds": 50.0}, "token refresh jitter MUST be below"),
    ]:
        with pytest.raises(ValueError, match=match):
            EventHubsKafkaBusConfig(
                **{"bootstrap_servers": "events.servicebus.windows.net:9093", **kwargs},  # type: ignore[arg-type]
            )

    with pytest.raises(ValueError, match="requires a workload identity"):
        EventHubsKafkaBus(identity=None, config=_config())

    with pytest.raises(ValueError, match="requires a token provider"):
        _transport_options(config=_config(), token_provider=None)

    provider = _EntraTokenProvider(_Identity(), "https://events.example/.default")
    with pytest.raises(RuntimeError, match="did not record token expiry"):
        _token_refresh_delay(token_provider=provider, group_id="g1", config=_config())

    class _FailingStop:
        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    await _stop_after_failure(_FailingStop(), operation="test_op")

    # Producer start failure and dead_letter failure
    start_fail = True

    class _FlakyProducer:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            if start_fail:
                raise RuntimeError("start boom")

        async def stop(self) -> None:
            return None

        async def send_and_wait(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("dlq boom")

    monkeypatch.setattr(event_bus_module, "AIOKafkaProducer", _FlakyProducer)
    bus = EventHubsKafkaBus(identity=_Identity(), config=_config())
    await bus.close()
    with pytest.raises(RuntimeError, match="start boom"):
        await bus.assert_publish_ready()

    start_fail = False
    await bus.assert_publish_ready()
    await bus.assert_publish_ready()
    with pytest.raises(RuntimeError, match="dlq boom"):
        await bus.dead_letter("executor.commands", "k", {}, "reason")
    await bus._discard_failed_producer(object(), operation="noop")  # type: ignore[arg-type]

    # Plaintext consumer iteration & _stop_consumer with _fetcher.close
    fetcher_closed = False

    class _PlainConsumer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.calls = 0
            self._fetcher = SimpleNamespace(close=self._close_fetcher)

        async def _close_fetcher(self) -> None:
            nonlocal fetcher_closed
            fetcher_closed = True

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def getone(self) -> object:
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    topic="executor.commands",
                    key=None,
                    value=b'{"x":1}',
                    offset=1,
                )
            raise RuntimeError("done")

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", _PlainConsumer)
    plain_cfg = EventHubsKafkaBusConfig(
        bootstrap_servers="127.0.0.1:19092", security_protocol="PLAINTEXT"
    )
    plain_it = _iter_consumer(
        topic="executor.commands",
        group_id="g1",
        config=plain_cfg,
        identity=None,
        audience=None,
        on_readiness=None,
    )
    env = await anext(plain_it)
    assert env.key == "" and env.payload == {"x": 1}
    with pytest.raises(RuntimeError, match="done"):
        await anext(plain_it)
    assert fetcher_closed is True

    # SASL consumer token refresh timeout break
    sasl_starts = 0

    class _TimeoutSaslConsumer:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.provider = kwargs["sasl_oauth_token_provider"]

        async def start(self) -> None:
            nonlocal sasl_starts
            sasl_starts += 1
            await self.provider.token()
            self.provider.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
            if sasl_starts > 1:
                raise RuntimeError("restarted after refresh")

        async def stop(self) -> None:
            return None

        async def getone(self) -> object:
            await asyncio.sleep(10)
            return None

    monkeypatch.setattr(event_bus_module, "AIOKafkaConsumer", _TimeoutSaslConsumer)
    sasl_it = bus.subscribe("executor.commands", "g1")
    with pytest.raises(RuntimeError, match="restarted after refresh"):
        await anext(sasl_it)
    await _stop_consumer(SimpleNamespace(_fetcher=None, stop=lambda: asyncio.sleep(0)))  # type: ignore[arg-type]
