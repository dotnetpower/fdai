"""Event Hubs Kafka transport and logical-topic routing for the worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import (
    AdapterReadiness,
    EventEnvelope,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)

_LOGICAL_TOPIC_FIELD = "_fdai_logical_topic"
_CONSUMER_HEALTH_POLL_SECONDS = 1.0


@dataclass(slots=True)
class _ConsumerGroupHealth:
    owners: int = 0
    last_success: float | None = None
    failure: str | None = None


class _ManagedIdentityTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    def __init__(self, credential: ManagedIdentityCredential, scope: str) -> None:
        self._credential = credential
        self._scope = scope
        self.expires_at: datetime | None = None

    async def token(self) -> str:
        token = await self._credential.get_token(self._scope)
        self.expires_at = datetime.fromtimestamp(token.expires_on, tz=UTC)
        value = token.token
        if not isinstance(value, str):
            raise RuntimeError("managed identity returned a non-string token")
        return value


@dataclass(frozen=True, slots=True)
class EventHubsKafkaConfig:
    bootstrap_servers: str
    client_id: str = "fdai-document-worker"
    auto_offset_reset: str = "earliest"
    dlq_suffix: str = ".dlq"

    def __post_init__(self) -> None:
        if not self.bootstrap_servers:
            raise ValueError("Kafka bootstrap servers MUST NOT be empty")
        if self.auto_offset_reset not in {"earliest", "latest"}:
            raise ValueError("auto_offset_reset MUST be earliest or latest")


class EventHubsKafkaBus:
    """Use the Event Hubs Kafka endpoint with managed identity authentication."""

    def __init__(
        self,
        *,
        config: EventHubsKafkaConfig,
        credential: ManagedIdentityCredential,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._credential = credential
        host = config.bootstrap_servers.split(",", 1)[0].strip().split(":", 1)[0]
        self._scope = f"https://{host}/.default"
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()
        self._monotonic = monotonic
        self._consumer_groups: dict[tuple[str, str], _ConsumerGroupHealth] = {}

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        await (await self._get_producer()).send_and_wait(
            topic,
            key=key.encode(),
            value=_encode(payload),
        )

    def readiness(self) -> AdapterReadiness:
        """Report validated Kafka composition without requesting an Azure token."""
        return configured_readiness("event-hubs-kafka")

    async def probe_readiness(self) -> AdapterReadiness:
        """Start the authenticated producer without publishing an event."""
        adapter = "event-hubs-kafka"
        try:
            await asyncio.wait_for(self._get_producer(), timeout=5.0)
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._iter_consumer(topic, group_id)

    def consumer_group_ready(
        self,
        topic: str,
        group_id: str,
        *,
        freshness_seconds: float,
    ) -> bool:
        """Return current ownership plus a fresh successful poll or record receipt."""
        state = self._consumer_groups.get((topic, group_id))
        return bool(
            state is not None
            and state.owners > 0
            and state.failure is None
            and state.last_success is not None
            and self._monotonic() - state.last_success <= freshness_seconds
        )

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
        reason: str,
    ) -> None:
        await self.publish(
            f"{topic}{self._config.dlq_suffix}",
            key,
            {"original_topic": topic, "reason": reason, "payload": dict(payload)},
        )

    async def close(self) -> None:
        async with self._producer_lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None
        await self._credential.close()

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._producer_lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._config.bootstrap_servers,
                    client_id=self._config.client_id,
                    security_protocol="SASL_SSL",
                    sasl_mechanism="OAUTHBEARER",
                    sasl_oauth_token_provider=_ManagedIdentityTokenProvider(
                        self._credential, self._scope
                    ),
                    ssl_context=ssl.create_default_context(),
                    api_version="2.0.0",
                    enable_idempotence=True,
                    acks="all",
                    linger_ms=5,
                    connections_max_idle_ms=180_000,
                    metadata_max_age_ms=180_000,
                    request_timeout_ms=60_000,
                    retry_backoff_ms=1_000,
                    max_request_size=1_000_000,
                )
                try:
                    await producer.start()
                except BaseException:
                    await producer.stop()
                    raise
                self._producer = producer
            return self._producer

    async def _iter_consumer(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        while True:
            token_provider = _ManagedIdentityTokenProvider(self._credential, self._scope)
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self._config.bootstrap_servers,
                group_id=group_id,
                client_id=self._config.client_id,
                security_protocol="SASL_SSL",
                sasl_mechanism="OAUTHBEARER",
                sasl_oauth_token_provider=token_provider,
                ssl_context=ssl.create_default_context(),
                api_version="2.0.0",
                enable_auto_commit=False,
                auto_offset_reset=self._config.auto_offset_reset,
                session_timeout_ms=30_000,
                heartbeat_interval_ms=3_000,
                connections_max_idle_ms=180_000,
                metadata_max_age_ms=180_000,
                request_timeout_ms=60_000,
                retry_backoff_ms=1_000,
            )
            started = False
            try:
                await consumer.start()
                self._consumer_started(topic, group_id)
                started = True
                refresh_at = asyncio.get_running_loop().time() + _refresh_delay(
                    token_provider, group_id
                )
                while True:
                    remaining = refresh_at - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        message = await asyncio.wait_for(
                            consumer.getone(),
                            timeout=min(remaining, _CONSUMER_HEALTH_POLL_SECONDS),
                        )
                    except TimeoutError:
                        assignment = getattr(consumer, "assignment", None)
                        if callable(assignment) and assignment():
                            self._consumer_succeeded(topic, group_id)
                        continue
                    key = (message.key or b"").decode(errors="replace")
                    payload = _decode(message.value)
                    if payload.get("_decode_error") is True:
                        await self.dead_letter(
                            message.topic,
                            key,
                            {"source_offset": message.offset},
                            "invalid_event_payload",
                        )
                        await consumer.commit()
                        self._consumer_succeeded(topic, group_id)
                        continue
                    self._consumer_succeeded(topic, group_id)
                    yield EventEnvelope(
                        topic=message.topic,
                        key=key,
                        payload=payload,
                        offset=message.offset,
                    )
                    await consumer.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consumer_failed(topic, group_id, exc)
                raise
            finally:
                if started:
                    self._consumer_stopped(topic, group_id)
                await consumer.stop()

    def _consumer_started(self, topic: str, group_id: str) -> None:
        state = self._consumer_groups.setdefault((topic, group_id), _ConsumerGroupHealth())
        if state.owners == 0:
            state.last_success = None
        state.owners += 1
        state.failure = None

    def _consumer_succeeded(self, topic: str, group_id: str) -> None:
        state = self._consumer_groups.setdefault((topic, group_id), _ConsumerGroupHealth())
        state.last_success = self._monotonic()
        state.failure = None

    def _consumer_failed(self, topic: str, group_id: str, exc: Exception) -> None:
        state = self._consumer_groups.setdefault((topic, group_id), _ConsumerGroupHealth())
        state.failure = type(exc).__name__

    def _consumer_stopped(self, topic: str, group_id: str) -> None:
        state = self._consumer_groups.setdefault((topic, group_id), _ConsumerGroupHealth())
        state.owners = max(0, state.owners - 1)


@dataclass(frozen=True, slots=True)
class MultiplexedEventBus:
    """Route reviewed logical topics through one physical pantheon topic."""

    bus: EventHubsKafkaBus
    logical_topics: frozenset[str]
    physical_topic: str

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        if topic not in self.logical_topics:
            await self.bus.publish(topic, key, payload)
            return
        enriched = dict(payload)
        enriched[_LOGICAL_TOPIC_FIELD] = topic
        await self.bus.publish(self.physical_topic, key, enriched)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    def consumer_group_ready(
        self,
        topic: str,
        group_id: str,
        *,
        freshness_seconds: float,
    ) -> bool:
        """Resolve logical routing before checking the running physical consumer group."""
        if topic not in self.logical_topics:
            return self.bus.consumer_group_ready(
                topic,
                group_id,
                freshness_seconds=freshness_seconds,
            )
        return self.bus.consumer_group_ready(
            self.physical_topic,
            _logical_group_id(topic, group_id),
            freshness_seconds=freshness_seconds,
        )

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        if topic not in self.logical_topics:
            async for event in self.bus.subscribe(topic, group_id):
                yield event
            return
        async for event in self.bus.subscribe(
            self.physical_topic, _logical_group_id(topic, group_id)
        ):
            if event.payload.get(_LOGICAL_TOPIC_FIELD) != topic:
                continue
            payload = dict(event.payload)
            payload.pop(_LOGICAL_TOPIC_FIELD, None)
            yield EventEnvelope(
                topic=topic,
                key=event.key,
                payload=payload,
                offset=event.offset,
            )

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
        reason: str,
    ) -> None:
        if topic not in self.logical_topics:
            await self.bus.dead_letter(topic, key, payload, reason)
            return
        enriched = dict(payload)
        enriched[_LOGICAL_TOPIC_FIELD] = topic
        await self.bus.dead_letter(self.physical_topic, key, enriched, reason)

    async def close(self) -> None:
        await self.bus.close()


def _refresh_delay(provider: _ManagedIdentityTokenProvider, group_id: str) -> float:
    if provider.expires_at is None:
        raise RuntimeError("OAUTHBEARER provider did not record token expiry")
    fraction = int.from_bytes(hashlib.sha256(group_id.encode()).digest()[:8], "big") / (
        (1 << 64) - 1
    )
    ttl = (provider.expires_at - datetime.now(tz=UTC)).total_seconds()
    return max(0.1, ttl - 45 + fraction * 15)


def _logical_group_id(topic: str, group_id: str) -> str:
    topic_hash = hashlib.sha256(topic.encode()).hexdigest()[:12]
    return f"{group_id}.{topic_hash}"


def _encode(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode()


def _decode(value: bytes | None) -> dict[str, object]:
    if value is None:
        return {}
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return {"_decode_error": True}
    return parsed if isinstance(parsed, dict) else {"_wrapped": parsed, "_decode_error": True}
