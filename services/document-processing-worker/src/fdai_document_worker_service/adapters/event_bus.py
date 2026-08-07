"""Event Hubs Kafka transport and logical-topic routing for the worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import AsyncIterator, Mapping
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
    ) -> None:
        self._config = config
        self._credential = credential
        host = config.bootstrap_servers.split(",", 1)[0].strip().split(":", 1)[0]
        self._scope = f"https://{host}/.default"
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()

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
            try:
                await consumer.start()
                refresh_at = asyncio.get_running_loop().time() + _refresh_delay(
                    token_provider, group_id
                )
                while True:
                    remaining = refresh_at - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        message = await asyncio.wait_for(consumer.getone(), timeout=remaining)
                    except TimeoutError:
                        break
                    key = (message.key or b"").decode(errors="replace")
                    yield EventEnvelope(
                        topic=message.topic,
                        key=key,
                        payload=_decode(message.value),
                        offset=message.offset,
                    )
                    await consumer.commit()
            finally:
                await consumer.stop()


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

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        if topic not in self.logical_topics:
            async for event in self.bus.subscribe(topic, group_id):
                yield event
            return
        topic_hash = hashlib.sha256(topic.encode()).hexdigest()[:12]
        async for event in self.bus.subscribe(self.physical_topic, f"{group_id}.{topic_hash}"):
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
