"""EventHubsKafkaBus - `EventBus` adapter for Azure Event Hubs Kafka wire.

Realizes ``docs/roadmap/architecture/csp-neutrality.md § 1`` (Kafka wire protocol)
against the Event Hubs endpoint on ``:9093``. Authenticates via SASL /
OAUTHBEARER with a token issued by an injected ``WorkloadIdentity``,
so composition-root swaps between the Managed-Identity adapter (prod)
and a fake (dev/tests).

Note: aiokafka's OAUTHBEARER hook returns only the token string, so it cannot
schedule reauthentication from the token expiry. This adapter retains the
injected ``IdentityToken.expires_at`` and recycles long-running consumers before
expiry; each new connection calls the token source again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Final, Literal

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.abc import AbstractTokenProvider

from fdai.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    EventPublishNotAttemptedError,
    PublishReceipt,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_AIOKAFKA_CONNECTION_LOGGER = logging.getLogger("aiokafka.conn")
_CONSUMER_STOP_TIMEOUT_SECONDS: Final[float] = 5.0
_CONSUMER_PROGRESS_INTERVAL_SECONDS: Final[float] = 60.0


def _default_ssl_context() -> ssl.SSLContext:
    """Standard TLS context for the Event Hubs Kafka endpoint.

    aiokafka refuses to construct a SASL_SSL client without a context; the
    default from :func:`ssl.create_default_context` uses the system trust
    store and enforces certificate verification against the Event Hubs
    hostname, matching what a browser would do.
    """
    return ssl.create_default_context()


def _audience_from_bootstrap(bootstrap_servers: str) -> str:
    """Derive the namespace-scoped OAUTHBEARER audience.

    Event Hubs data-plane REJECTS a token whose ``aud`` is the generic
    ``https://eventhubs.azure.net`` - it parses "eventhubs" as a
    tenant/namespace name and fails with
    ``SaslAuthenticationFailed: Invalid tenant name 'eventhubs'``. The
    working audience is the namespace FQDN, which every Event Hubs
    tenant accepts:

        https://<namespace>.servicebus.windows.net/.default

    We strip an optional port (``:9093``) from the first bootstrap
    entry and prepend ``https://`` + append ``/.default`` so the scope
    lands in the OIDC-compatible shape.
    """
    first = bootstrap_servers.split(",")[0].strip()
    host = first.split(":", 1)[0]
    if not host:
        raise ValueError(f"cannot derive audience from bootstrap_servers={bootstrap_servers!r}")
    return f"https://{host}/.default"


@dataclass(frozen=True, slots=True)
class EventHubsKafkaBusConfig:
    """Endpoint + auth binding for one Event Hubs namespace."""

    bootstrap_servers: str
    """``<namespace>.servicebus.windows.net:9093``."""

    security_protocol: Literal["SASL_SSL", "PLAINTEXT"] = "SASL_SSL"

    client_id: str = "fdai-core"
    """Advertised client id - no functional impact, aids broker logs."""

    session_timeout_ms: int = 30_000
    heartbeat_interval_ms: int = 3_000
    dlq_suffix: str = ".dlq"
    """Kafka has no native DLQ; ``<topic>.dlq`` is the convention documented
    in csp-neutrality.md § 1. MUST match ``KafkaConfig.topic_dlq_suffix``."""

    audience: str | None = None
    """OAUTHBEARER token audience. Default derives it from the namespace
    FQDN in ``bootstrap_servers`` (see :func:`_audience_from_bootstrap`).
    A fork MAY pin it explicitly for a non-Azure endpoint (Confluent,
    Redpanda, ...)."""

    auto_offset_reset: str = "latest"
    """Initial position for a new consumer group. Durable worker groups use
    ``earliest`` so events published before their first replica starts are not lost."""

    connections_max_idle_ms: int = 180_000
    """Recycle idle sockets before Event Hubs closes them after 240 seconds."""

    metadata_max_age_ms: int = 180_000
    """Refresh metadata before the same Event Hubs 240-second connection window."""

    request_timeout_ms: int = 60_000
    """Event Hubs recommendation for idempotent producer requests."""

    retry_backoff_ms: int = 1_000
    """Bound reconnect retries after a broker or network interruption."""

    max_request_size: int = 1_000_000
    """Stay below the Event Hubs 1,046,528-byte request ceiling."""

    token_refresh_margin_seconds: float = 45.0
    token_refresh_jitter_seconds: float = 15.0
    """Recycle consumers 30-45 seconds before their Entra token expires."""

    commit_max_records: int = 50
    commit_interval_seconds: float = 5.0
    """Bound how much redelivery a lost consumer causes. A commit costs a broker
    round-trip (~0.8s against Event Hubs), so committing per message caps ingest
    throughput no matter how fast events are processed."""

    _EVENT_HUBS_IDLE_CLOSE_MS: ClassVar[int] = 240_000
    _EVENT_HUBS_REQUEST_TIMEOUT_FLOOR_MS: ClassVar[int] = 60_000
    _EVENT_HUBS_MAX_REQUEST_SIZE: ClassVar[int] = 1_000_000
    _MIN_RETRY_BACKOFF_MS: ClassVar[int] = 1_000

    def __post_init__(self) -> None:
        if self.security_protocol not in {"SASL_SSL", "PLAINTEXT"}:
            raise ValueError("security_protocol MUST be SASL_SSL or PLAINTEXT")
        if self.auto_offset_reset not in {"earliest", "latest"}:
            raise ValueError("auto_offset_reset MUST be earliest or latest")
        if self.session_timeout_ms <= 0:
            raise ValueError("session_timeout_ms MUST be positive")
        if self.heartbeat_interval_ms <= 0:
            raise ValueError("heartbeat_interval_ms MUST be positive")
        if self.heartbeat_interval_ms >= self.session_timeout_ms:
            raise ValueError("heartbeat_interval_ms MUST be less than session_timeout_ms")
        if not self.dlq_suffix:
            raise ValueError("dlq_suffix MUST NOT be empty")
        if not 0 < self.connections_max_idle_ms < self._EVENT_HUBS_IDLE_CLOSE_MS:
            raise ValueError(
                "connections_max_idle_ms MUST be positive and below the "
                "Event Hubs 240000 ms idle-close window"
            )
        if not 0 < self.metadata_max_age_ms < self._EVENT_HUBS_IDLE_CLOSE_MS:
            raise ValueError(
                "metadata_max_age_ms MUST be positive and below the "
                "Event Hubs 240000 ms idle-close window"
            )
        if self.request_timeout_ms < self._EVENT_HUBS_REQUEST_TIMEOUT_FLOOR_MS:
            raise ValueError("request_timeout_ms MUST be at least 60000 ms")
        if self.retry_backoff_ms < self._MIN_RETRY_BACKOFF_MS:
            raise ValueError("retry_backoff_ms MUST be at least 1000 ms")
        if not 0 < self.max_request_size <= self._EVENT_HUBS_MAX_REQUEST_SIZE:
            raise ValueError("max_request_size MUST be in [1, 1000000]")
        if self.token_refresh_margin_seconds <= 0:
            raise ValueError("token_refresh_margin_seconds MUST be positive")
        if self.commit_max_records < 1:
            raise ValueError("commit_max_records MUST be at least 1")
        if self.commit_interval_seconds <= 0:
            raise ValueError("commit_interval_seconds MUST be positive")
        if not 0 <= self.token_refresh_jitter_seconds < self.token_refresh_margin_seconds:
            raise ValueError(
                "token_refresh_jitter_seconds MUST be non-negative and less than "
                "token_refresh_margin_seconds"
            )


class _EntraTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    """Bridge :class:`WorkloadIdentity` into aiokafka's token contract."""

    def __init__(self, identity: WorkloadIdentity, audience: str) -> None:
        self._identity = identity
        self._audience = audience
        self.expires_at: datetime | None = None

    async def token(self) -> str:
        entra = await self._identity.get_token(self._audience)
        self.expires_at = entra.expires_at
        return entra.token


class EventHubsKafkaBus(EventBus):
    """Kafka-wire ``EventBus`` bound to Azure Event Hubs."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity | None,
        config: EventHubsKafkaBusConfig,
    ) -> None:
        if not config.bootstrap_servers:
            raise ValueError("bootstrap_servers MUST NOT be empty")
        # aiokafka emits one context-free success line per broker socket. A
        # consumer commonly opens bootstrap, coordinator, and fetch sockets,
        # so INFO output becomes indistinguishable noise during fan-out startup.
        # Keep dependency warnings/errors and emit one owned record per logical
        # consumer after startup instead.
        _AIOKAFKA_CONNECTION_LOGGER.setLevel(logging.WARNING)
        if config.security_protocol == "SASL_SSL" and identity is None:
            raise ValueError("SASL_SSL Kafka transport requires a workload identity")
        self._identity: Final[WorkloadIdentity | None] = identity
        self._config: Final[EventHubsKafkaBusConfig] = config
        self._audience: Final[str | None] = (
            config.audience or _audience_from_bootstrap(config.bootstrap_servers)
            if config.security_protocol == "SASL_SSL"
            else None
        )
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._producer_lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._config.bootstrap_servers,
                    client_id=self._config.client_id,
                    **_transport_options(
                        config=self._config,
                        token_provider=(
                            _EntraTokenProvider(self._identity, self._audience)
                            if self._identity is not None and self._audience is not None
                            else None
                        ),
                    ),
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

    async def close(self) -> None:
        """Idempotent teardown for the shared producer."""
        async with self._producer_lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

    async def _discard_failed_producer(
        self,
        producer: AIOKafkaProducer,
        *,
        operation: str,
    ) -> None:
        async with self._producer_lock:
            if self._producer is not producer:
                return
            self._producer = None
            await _stop_after_failure(producer, operation=operation)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        try:
            producer = await self._get_producer()
            record = _encode(payload)
            record_key = key.encode("utf-8")
        except Exception as exc:
            raise EventPublishNotAttemptedError(
                f"analyzer record was not sent to {topic}: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            record_meta = await producer.send_and_wait(topic, value=record, key=record_key)
        except BaseException:
            await self._discard_failed_producer(producer, operation="publish")
            raise
        return PublishReceipt(
            topic=record_meta.topic,
            partition=record_meta.partition,
            offset=record_meta.offset,
        )

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
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
        dlq = f"{topic}{self._config.dlq_suffix}"
        _LOGGER.warning(
            "dead_lettering",
            extra={"topic": topic, "dlq": dlq, "reason": reason, "key": key},
        )
        dlq_payload = {
            "original_topic": topic,
            "reason": reason,
            "payload": dict(payload),
        }
        producer = await self._get_producer()
        try:
            await producer.send_and_wait(
                dlq,
                value=_encode(dlq_payload),
                key=key.encode("utf-8"),
            )
        except BaseException:
            await self._discard_failed_producer(producer, operation="dead_letter")
            raise


async def _iter_consumer(
    *,
    topic: str,
    group_id: str,
    config: EventHubsKafkaBusConfig,
    identity: WorkloadIdentity | None,
    audience: str | None,
) -> AsyncIterator[EventEnvelope]:
    """Own its consumer lifecycle so the caller only sees the envelopes."""
    while True:
        progress_monitor: asyncio.Task[None] | None = None
        token_provider = (
            _EntraTokenProvider(identity, audience)
            if identity is not None and audience is not None
            else None
        )
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=config.bootstrap_servers,
            group_id=group_id,
            client_id=config.client_id,
            **_transport_options(config=config, token_provider=token_provider),
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
                    "auth_mechanism": (
                        "OAUTHBEARER" if token_provider is not None else "PLAINTEXT"
                    ),
                },
            )
            progress_monitor = asyncio.create_task(
                _monitor_consumer_progress(
                    consumer,
                    topic=topic,
                    group_id=group_id,
                ),
                name=f"event-bus-progress:{group_id}",
            )
            if token_provider is None:
                # Closing the nested stream here keeps consumer teardown inside the
                # caller's task instead of deferring it to loop finalization.
                async with aclosing(
                    _consume_messages(
                        consumer,
                        commit_max_records=config.commit_max_records,
                        commit_interval_seconds=config.commit_interval_seconds,
                    )
                ) as stream:
                    async for envelope in stream:
                        yield envelope
                return
            refresh_at = asyncio.get_running_loop().time() + _token_refresh_delay(
                token_provider=token_provider,
                group_id=group_id,
                config=config,
            )
            uncommitted = 0
            partition_offsets: dict[int, int] = {}
            last_commit_at = asyncio.get_running_loop().time()
            while True:
                now = asyncio.get_running_loop().time()
                refresh_remaining = refresh_at - now
                if refresh_remaining <= 0:
                    break
                commit_remaining = (
                    config.commit_interval_seconds - (now - last_commit_at)
                    if uncommitted
                    else refresh_remaining
                )
                if uncommitted and commit_remaining <= 0:
                    await _commit_consumer_progress(
                        consumer,
                        topic=topic,
                        group_id=group_id,
                        partition_offsets=partition_offsets,
                    )
                    uncommitted = 0
                    partition_offsets.clear()
                    last_commit_at = now
                    continue
                try:
                    message = await asyncio.wait_for(
                        consumer.getone(),
                        timeout=min(refresh_remaining, commit_remaining),
                    )
                except TimeoutError:
                    if uncommitted:
                        continue
                    break
                key = _decode_key(message.key)
                payload = _decode(message.value, topic=message.topic, key=key)
                yield EventEnvelope(
                    topic=message.topic,
                    key=key,
                    payload=payload,
                    offset=message.offset,
                )
                partition = getattr(message, "partition", None)
                if isinstance(partition, int) and partition >= 0:
                    partition_offsets[partition] = message.offset
                # At-least-once: commit only after the caller finished iterating
                # to the yield point. If the caller crashes mid-processing, the
                # broker will redeliver the message and the ControlLoop's
                # idempotency_key dedupe will make the retry a no-op. That same
                # dedupe is what lets one commit cover a bounded batch instead of
                # paying a broker round-trip for every single event.
                uncommitted += 1
                now = asyncio.get_running_loop().time()
                if (
                    uncommitted >= config.commit_max_records
                    or now - last_commit_at >= config.commit_interval_seconds
                ):
                    await _commit_consumer_progress(
                        consumer,
                        topic=topic,
                        group_id=group_id,
                        partition_offsets=partition_offsets,
                    )
                    uncommitted = 0
                    partition_offsets.clear()
                    last_commit_at = now
            if uncommitted:
                await _commit_consumer_progress(
                    consumer,
                    topic=topic,
                    group_id=group_id,
                    partition_offsets=partition_offsets,
                )
            _LOGGER.debug("event_bus_consumer_token_refresh", extra={"group_id": group_id})
        finally:
            if progress_monitor is not None:
                progress_monitor.cancel()
                await asyncio.gather(progress_monitor, return_exceptions=True)
            await _stop_consumer(consumer, topic=topic, group_id=group_id)


async def _monitor_consumer_progress(
    consumer: AIOKafkaConsumer,
    *,
    topic: str,
    group_id: str,
    interval_seconds: float = _CONSUMER_PROGRESS_INTERVAL_SECONDS,
) -> None:
    """Export broker-backed lag even while downstream processing is stalled."""
    last_end_offsets: dict[TopicPartition, int] = {}
    last_lags: dict[TopicPartition, int | None] = {}
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with asyncio.timeout(interval_seconds):
                partitions = tuple(
                    sorted(consumer.assignment(), key=lambda partition: partition.partition)
                )
                if not partitions:
                    continue
                end_offsets = await consumer.end_offsets(partitions)
                for topic_partition in partitions:
                    highwater_offset = end_offsets.get(topic_partition)
                    if (
                        highwater_offset == last_end_offsets.get(topic_partition)
                        and last_lags.get(topic_partition) == 0
                    ):
                        continue
                    committed_offset = await consumer.committed(topic_partition)
                    if committed_offset is None:
                        committed_offset = await consumer.position(topic_partition)
                    lag = (
                        max(0, highwater_offset - committed_offset)
                        if isinstance(committed_offset, int)
                        and committed_offset >= 0
                        and isinstance(highwater_offset, int)
                        else None
                    )
                    last_end_offsets[topic_partition] = highwater_offset
                    last_lags[topic_partition] = lag
                    _log_consumer_progress(
                        topic=topic,
                        group_id=group_id,
                        partition=topic_partition.partition,
                        committed_offset=committed_offset,
                        highwater_offset=highwater_offset,
                        lag=lag,
                        progress_kind="heartbeat",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - observability cannot stop ingestion
            _LOGGER.warning(
                "event_bus_consumer_progress_failed",
                extra={"topic": topic, "consumer_group": group_id},
                exc_info=True,
            )


async def _commit_consumer_progress(
    consumer: AIOKafkaConsumer,
    *,
    topic: str,
    group_id: str,
    partition_offsets: Mapping[int, int],
) -> None:
    """Commit one batch and export sanitized per-partition progress."""
    await consumer.commit()
    highwater_for = getattr(consumer, "highwater", None)
    for partition, offset in sorted(partition_offsets.items()):
        topic_partition = TopicPartition(topic, partition)
        highwater = _assigned_highwater(consumer, topic_partition, highwater_for)
        committed_offset = offset + 1
        lag = max(0, highwater - committed_offset) if isinstance(highwater, int) else None
        _log_consumer_progress(
            topic=topic,
            group_id=group_id,
            partition=partition,
            committed_offset=committed_offset,
            highwater_offset=highwater,
            lag=lag,
            progress_kind="commit",
        )


def _assigned_highwater(
    consumer: AIOKafkaConsumer,
    topic_partition: TopicPartition,
    highwater_for: object,
) -> int | None:
    """Read highwater only while the consumer still owns the partition."""
    if not callable(highwater_for):
        return None
    assignment_for = getattr(consumer, "assignment", None)
    if callable(assignment_for) and topic_partition not in assignment_for():
        return None
    try:
        highwater = highwater_for(topic_partition)
    except AssertionError:
        return None
    return highwater if isinstance(highwater, int) else None


def _log_consumer_progress(
    *,
    topic: str,
    group_id: str,
    partition: int,
    committed_offset: int | None,
    highwater_offset: int | None,
    lag: int | None,
    progress_kind: Literal["commit", "heartbeat"],
) -> None:
    _LOGGER.info(
        "event_bus_consumer_progress",
        extra={
            "topic": topic,
            "consumer_group": group_id,
            "partition": partition,
            "committed_offset": committed_offset,
            "highwater_offset": highwater_offset,
            "consumer_lag": lag,
            "progress_kind": progress_kind,
        },
    )


async def _consume_messages(
    consumer: AIOKafkaConsumer,
    *,
    commit_max_records: int,
    commit_interval_seconds: float,
) -> AsyncGenerator[EventEnvelope, None]:
    uncommitted = 0
    last_commit_at = asyncio.get_running_loop().time()
    while True:
        if uncommitted:
            remaining = commit_interval_seconds - (
                asyncio.get_running_loop().time() - last_commit_at
            )
            if remaining <= 0:
                await consumer.commit()
                uncommitted = 0
                last_commit_at = asyncio.get_running_loop().time()
                continue
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=remaining)
            except TimeoutError:
                await consumer.commit()
                uncommitted = 0
                last_commit_at = asyncio.get_running_loop().time()
                continue
        else:
            message = await consumer.getone()
        key = _decode_key(message.key)
        yield EventEnvelope(
            topic=message.topic,
            key=key,
            payload=_decode(message.value, topic=message.topic, key=key),
            offset=message.offset,
        )
        uncommitted += 1
        if uncommitted >= commit_max_records:
            await consumer.commit()
            uncommitted = 0
            last_commit_at = asyncio.get_running_loop().time()


def _transport_options(
    *,
    config: EventHubsKafkaBusConfig,
    token_provider: _EntraTokenProvider | None,
) -> dict[str, object]:
    if config.security_protocol == "PLAINTEXT":
        return {"security_protocol": "PLAINTEXT"}
    if token_provider is None:
        raise ValueError("SASL_SSL Kafka transport requires a token provider")
    return {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "OAUTHBEARER",
        "sasl_oauth_token_provider": token_provider,
        "ssl_context": _default_ssl_context(),
    }


async def _stop_consumer(
    consumer: AIOKafkaConsumer,
    *,
    topic: str,
    group_id: str,
) -> None:
    """Cancel fetch I/O and bound the broker-dependent group leave.

    Teardown runs inside the consumer's own task, usually while a cancellation is
    unwinding it. Raising here would replace that cancellation with a crash, so a
    broker failure is recorded against its topic and consumer group instead.
    """
    fetcher = getattr(consumer, "_fetcher", None)
    close_fetcher = getattr(fetcher, "close", None)
    if callable(close_fetcher):
        await close_fetcher()
    try:
        async with asyncio.timeout(_CONSUMER_STOP_TIMEOUT_SECONDS):
            await consumer.stop()
    except TimeoutError:
        _LOGGER.warning(
            "event_bus_consumer_stop_timed_out",
            extra={
                "timeout_seconds": _CONSUMER_STOP_TIMEOUT_SECONDS,
                "topic": topic,
                "consumer_group": group_id,
            },
        )
        client = getattr(consumer, "_client", None)
        close_client = getattr(client, "close", None)
        if callable(close_client):
            await close_client()
    except Exception:  # noqa: BLE001 - a failed leave must not become a consumer crash
        _LOGGER.warning(
            "event_bus_consumer_stop_failed",
            extra={"topic": topic, "consumer_group": group_id},
            exc_info=True,
        )


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
    """Best-effort cleanup that never masks the triggering transport failure."""
    try:
        await client.stop()
    except BaseException:  # cleanup must preserve the original failure, including cancellation
        _LOGGER.warning("event_bus_cleanup_failed", extra={"operation": operation}, exc_info=True)


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decode(value: bytes | None, *, topic: str = "", key: str = "") -> Mapping[str, Any]:
    """Best-effort JSON decode; log-and-flag malformed payloads.

    Kafka delivers raw bytes; if a producer ships an invalid or non-object
    JSON payload we cannot drop the message silently (that hides operator
    signal) and cannot raise from a hot-path generator (that stalls the
    consumer group). Instead we emit a WARNING with the topic and key so
    an operator can locate the poison message, and return a sentinel
    envelope shape that downstream ``payload.get("resource")`` lookups
    resolve to ``None`` - the trust router abstains and the risk gate's
    fail-toward-safety path takes it from there.
    """
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        _LOGGER.warning(
            "event_bus_decode_error",
            extra={"topic": topic, "key": key, "bytes": len(value)},
        )
        return {"_raw": value.decode("utf-8", errors="replace"), "_decode_error": True}
    if not isinstance(parsed, dict):
        _LOGGER.warning(
            "event_bus_non_object_payload",
            extra={"topic": topic, "key": key, "type": type(parsed).__name__},
        )
        return {"_wrapped": parsed, "_decode_error": True}
    return parsed


def _decode_key(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace")


__all__ = ["EventHubsKafkaBus", "EventHubsKafkaBusConfig"]
