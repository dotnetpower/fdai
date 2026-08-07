"""Azure Event Hubs adapter over the Kafka wire protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import ssl
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Final

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider

from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.isolated_executor.event_bus")


def _default_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _audience_from_bootstrap(bootstrap_servers: str) -> str:
    first = bootstrap_servers.split(",")[0].strip()
    host = first.split(":", 1)[0]
    if not host:
        raise ValueError("cannot derive Event Hubs audience from bootstrap_servers")
    return f"https://{host}/.default"


@dataclass(frozen=True, slots=True)
class EventHubsKafkaBusConfig:
    """Bounded Kafka transport and OAuth settings for one namespace."""

    bootstrap_servers: str
    client_id: str = "fdai-isolated-executor"
    session_timeout_ms: int = 30_000
    heartbeat_interval_ms: int = 3_000
    dlq_suffix: str = ".dlq"
    audience: str | None = None
    auto_offset_reset: str = "latest"
    connections_max_idle_ms: int = 180_000
    metadata_max_age_ms: int = 180_000
    request_timeout_ms: int = 60_000
    retry_backoff_ms: int = 1_000
    max_request_size: int = 1_000_000
    token_refresh_margin_seconds: float = 45.0
    token_refresh_jitter_seconds: float = 15.0

    _EVENT_HUBS_IDLE_CLOSE_MS: ClassVar[int] = 240_000
    _EVENT_HUBS_REQUEST_TIMEOUT_FLOOR_MS: ClassVar[int] = 60_000
    _EVENT_HUBS_MAX_REQUEST_SIZE: ClassVar[int] = 1_000_000
    _MIN_RETRY_BACKOFF_MS: ClassVar[int] = 1_000

    def __post_init__(self) -> None:
        if not self.bootstrap_servers:
            raise ValueError("bootstrap_servers MUST NOT be empty")
        if self.auto_offset_reset not in {"earliest", "latest"}:
            raise ValueError("auto_offset_reset MUST be earliest or latest")
        if self.session_timeout_ms <= 0:
            raise ValueError("session_timeout_ms MUST be positive")
        if not 0 < self.heartbeat_interval_ms < self.session_timeout_ms:
            raise ValueError("heartbeat_interval_ms MUST be positive and below session timeout")
        if not self.dlq_suffix:
            raise ValueError("dlq_suffix MUST NOT be empty")
        if not 0 < self.connections_max_idle_ms < self._EVENT_HUBS_IDLE_CLOSE_MS:
            raise ValueError("connections_max_idle_ms MUST be below 240000 ms")
        if not 0 < self.metadata_max_age_ms < self._EVENT_HUBS_IDLE_CLOSE_MS:
            raise ValueError("metadata_max_age_ms MUST be below 240000 ms")
        if self.request_timeout_ms < self._EVENT_HUBS_REQUEST_TIMEOUT_FLOOR_MS:
            raise ValueError("request_timeout_ms MUST be at least 60000 ms")
        if self.retry_backoff_ms < self._MIN_RETRY_BACKOFF_MS:
            raise ValueError("retry_backoff_ms MUST be at least 1000 ms")
        if not 0 < self.max_request_size <= self._EVENT_HUBS_MAX_REQUEST_SIZE:
            raise ValueError("max_request_size MUST be in [1, 1000000]")
        if self.token_refresh_margin_seconds <= 0:
            raise ValueError("token_refresh_margin_seconds MUST be positive")
        if not 0 <= self.token_refresh_jitter_seconds < self.token_refresh_margin_seconds:
            raise ValueError("token refresh jitter MUST be below the refresh margin")


class _EntraTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    def __init__(self, identity: WorkloadIdentity, audience: str) -> None:
        self._identity = identity
        self._audience = audience
        self.expires_at: datetime | None = None

    async def token(self) -> str:
        token = await self._identity.get_token(self._audience)
        self.expires_at = token.expires_at
        return token.token


class EventHubsKafkaBus(EventBus):
    """Publish and consume at-least-once records through Event Hubs Kafka."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        config: EventHubsKafkaBusConfig,
    ) -> None:
        logging.getLogger("aiokafka.conn").setLevel(logging.WARNING)
        self._identity: Final[WorkloadIdentity] = identity
        self._config: Final[EventHubsKafkaBusConfig] = config
        self._audience: Final[str] = config.audience or _audience_from_bootstrap(
            config.bootstrap_servers
        )
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        """Publish one keyed record and return its broker acknowledgement."""

        producer = await self._get_producer()
        try:
            metadata = await producer.send_and_wait(
                topic,
                value=_encode(payload),
                key=key.encode("utf-8"),
            )
        except BaseException:
            await self._discard_failed_producer(producer, operation="publish")
            raise
        return PublishReceipt(
            topic=metadata.topic,
            partition=metadata.partition,
            offset=metadata.offset,
        )

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        """Return a consumer that commits only after each yielded record is handled."""

        return _iter_consumer(
            topic=topic,
            group_id=group_id,
            config=self._config,
            identity=self._identity,
            audience=self._audience,
        )

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Publish a poison record to the configured sibling DLQ."""

        dlq = f"{topic}{self._config.dlq_suffix}"
        _LOGGER.warning(
            "dead_lettering",
            extra={
                "topic": topic,
                "dlq": dlq,
                "reason": reason,
                "key_digest": hashlib.sha256(key.encode()).hexdigest()[:16],
            },
        )
        producer = await self._get_producer()
        try:
            await producer.send_and_wait(
                dlq,
                value=_encode(
                    {"original_topic": topic, "reason": reason, "payload": dict(payload)}
                ),
                key=key.encode("utf-8"),
            )
        except BaseException:
            await self._discard_failed_producer(producer, operation="dead_letter")
            raise

    async def close(self) -> None:
        """Idempotently stop the shared producer."""

        async with self._producer_lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._producer_lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._config.bootstrap_servers,
                    client_id=self._config.client_id,
                    security_protocol="SASL_SSL",
                    sasl_mechanism="OAUTHBEARER",
                    sasl_oauth_token_provider=_EntraTokenProvider(self._identity, self._audience),
                    ssl_context=_default_ssl_context(),
                    api_version="2.0.0",
                    enable_idempotence=True,
                    linger_ms=5,
                    acks="all",
                    connections_max_idle_ms=self._config.connections_max_idle_ms,
                    metadata_max_age_ms=self._config.metadata_max_age_ms,
                    request_timeout_ms=self._config.request_timeout_ms,
                    retry_backoff_ms=self._config.retry_backoff_ms,
                    max_request_size=self._config.max_request_size,
                )
                try:
                    await producer.start()
                except BaseException:
                    await _stop_after_failure(producer, operation="producer_start")
                    raise
                self._producer = producer
            return self._producer

    async def _discard_failed_producer(
        self,
        producer: AIOKafkaProducer,
        *,
        operation: str,
    ) -> None:
        async with self._producer_lock:
            if self._producer is producer:
                self._producer = None
                await _stop_after_failure(producer, operation=operation)


async def _iter_consumer(
    *,
    topic: str,
    group_id: str,
    config: EventHubsKafkaBusConfig,
    identity: WorkloadIdentity,
    audience: str,
) -> AsyncIterator[EventEnvelope]:
    while True:
        token_provider = _EntraTokenProvider(identity, audience)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=config.bootstrap_servers,
            group_id=group_id,
            client_id=config.client_id,
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauth_token_provider=token_provider,
            ssl_context=_default_ssl_context(),
            api_version="2.0.0",
            session_timeout_ms=config.session_timeout_ms,
            heartbeat_interval_ms=config.heartbeat_interval_ms,
            enable_auto_commit=False,
            auto_offset_reset=config.auto_offset_reset,
            connections_max_idle_ms=config.connections_max_idle_ms,
            metadata_max_age_ms=config.metadata_max_age_ms,
            request_timeout_ms=config.request_timeout_ms,
            retry_backoff_ms=config.retry_backoff_ms,
        )
        try:
            await consumer.start()
            _LOGGER.info(
                "event_bus_consumer_started",
                extra={
                    "topic": topic,
                    "consumer_group": group_id,
                    "client_id": config.client_id,
                    "auth_mechanism": "OAUTHBEARER",
                },
            )
            refresh_at = asyncio.get_running_loop().time() + _token_refresh_delay(
                token_provider=token_provider,
                group_id=group_id,
                config=config,
            )
            while True:
                remaining = refresh_at - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    message = await asyncio.wait_for(consumer.getone(), timeout=remaining)
                except TimeoutError:
                    break
                key = _decode_key(message.key)
                yield EventEnvelope(
                    topic=message.topic,
                    key=key,
                    payload=_decode(message.value, topic=message.topic),
                    offset=message.offset,
                )
                await consumer.commit()
        finally:
            await _stop_consumer(consumer)


async def _stop_consumer(consumer: AIOKafkaConsumer) -> None:
    fetcher = getattr(consumer, "_fetcher", None)
    close_fetcher = getattr(fetcher, "close", None)
    if callable(close_fetcher):
        await close_fetcher()
    await consumer.stop()


def _token_refresh_delay(
    *,
    token_provider: _EntraTokenProvider,
    group_id: str,
    config: EventHubsKafkaBusConfig,
) -> float:
    expires_at = token_provider.expires_at
    if expires_at is None:
        raise RuntimeError("OAUTHBEARER provider did not record token expiry during startup")
    digest = hashlib.sha256(group_id.encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    jitter = fraction * config.token_refresh_jitter_seconds
    ttl = (expires_at - datetime.now(tz=UTC)).total_seconds()
    return max(0.1, ttl - config.token_refresh_margin_seconds + jitter)


async def _stop_after_failure(client: Any, *, operation: str) -> None:
    try:
        await client.stop()
    except BaseException:
        _LOGGER.warning(
            "event_bus_cleanup_failed",
            extra={"operation": operation},
            exc_info=True,
        )


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decode(value: bytes | None, *, topic: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        _LOGGER.warning("event_bus_decode_error", extra={"topic": topic, "bytes": len(value)})
        return {"_decode_error": True, "_raw_bytes": len(value)}
    if not isinstance(parsed, dict):
        _LOGGER.warning(
            "event_bus_non_object_payload",
            extra={"topic": topic, "type": type(parsed).__name__},
        )
        return {"_decode_error": True, "_payload_type": type(parsed).__name__}
    return parsed


def _decode_key(value: bytes | None) -> str:
    return "" if value is None else value.decode("utf-8", errors="replace")


__all__ = ["EventHubsKafkaBus", "EventHubsKafkaBusConfig"]
