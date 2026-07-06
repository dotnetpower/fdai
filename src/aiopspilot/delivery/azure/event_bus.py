"""EventHubsKafkaBus — `EventBus` adapter for Azure Event Hubs Kafka wire.

Realizes ``docs/roadmap/csp-neutrality.md § 1`` (Kafka wire protocol)
against the Event Hubs endpoint on ``:9093``. Authenticates via SASL /
OAUTHBEARER with a token issued by an injected ``WorkloadIdentity``,
so composition-root swaps between the Managed-Identity adapter (prod)
and a fake (dev/tests).

Note: aiokafka's OAUTHBEARER hook expects a synchronous ``token_provider``
callable that returns a ``(token, expires_epoch)`` tuple. This adapter
warms the token cache eagerly at ``start()`` and refreshes at each
producer/consumer bootstrap. Long-running consumers rely on the SASL
extension's built-in reconnect + reauth loop; the token endpoint is
called again automatically when the broker rejects an expired token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider

from aiopspilot.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    PublishReceipt,
)
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)


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
    ``https://eventhubs.azure.net`` — it parses "eventhubs" as a
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

    client_id: str = "aiopspilot-core"
    """Advertised client id — no functional impact, aids broker logs."""

    session_timeout_ms: int = 30_000
    heartbeat_interval_ms: int = 10_000
    dlq_suffix: str = ".dlq"
    """Kafka has no native DLQ; ``<topic>.dlq`` is the convention documented
    in csp-neutrality.md § 1. MUST match ``KafkaConfig.topic_dlq_suffix``."""

    audience: str | None = None
    """OAUTHBEARER token audience. Default derives it from the namespace
    FQDN in ``bootstrap_servers`` (see :func:`_audience_from_bootstrap`).
    A fork MAY pin it explicitly for a non-Azure endpoint (Confluent,
    Redpanda, ...)."""


class _EntraTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    """Bridge :class:`WorkloadIdentity` into aiokafka's token contract."""

    def __init__(self, identity: WorkloadIdentity, audience: str) -> None:
        self._identity = identity
        self._audience = audience

    async def token(self) -> str:
        entra = await self._identity.get_token(self._audience)
        return entra.token


class EventHubsKafkaBus(EventBus):
    """Kafka-wire ``EventBus`` bound to Azure Event Hubs."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        config: EventHubsKafkaBusConfig,
    ) -> None:
        if not config.bootstrap_servers:
            raise ValueError("bootstrap_servers MUST NOT be empty")
        self._identity: Final[WorkloadIdentity] = identity
        self._config: Final[EventHubsKafkaBusConfig] = config
        self._audience: Final[str] = config.audience or _audience_from_bootstrap(
            config.bootstrap_servers
        )
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()

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
                )
                await producer.start()
                self._producer = producer
            return self._producer

    async def close(self) -> None:
        """Idempotent teardown for the shared producer."""
        async with self._producer_lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        producer = await self._get_producer()
        record_meta = await producer.send_and_wait(
            topic,
            value=_encode(payload),
            key=key.encode("utf-8"),
        )
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
        # Reason rides on a header so downstream tooling can filter without
        # rewriting the payload — the payload MUST arrive at the DLQ as-is
        # per csp-neutrality.md § 1.
        producer = await self._get_producer()
        await producer.send_and_wait(
            dlq,
            value=_encode(payload),
            key=key.encode("utf-8"),
            headers=[("dlq_reason", reason.encode("utf-8"))],
        )


async def _iter_consumer(
    *,
    topic: str,
    group_id: str,
    config: EventHubsKafkaBusConfig,
    identity: WorkloadIdentity,
    audience: str,
) -> AsyncIterator[EventEnvelope]:
    """Own its consumer lifecycle so the caller only sees the envelopes."""
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=config.bootstrap_servers,
        group_id=group_id,
        client_id=config.client_id,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=_EntraTokenProvider(identity, audience),
        ssl_context=_default_ssl_context(),
        api_version="2.0.0",
        session_timeout_ms=config.session_timeout_ms,
        heartbeat_interval_ms=config.heartbeat_interval_ms,
        enable_auto_commit=False,
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for message in consumer:
            payload = _decode(message.value)
            key = _decode_key(message.key)
            yield EventEnvelope(
                topic=message.topic,
                key=key,
                payload=payload,
                offset=message.offset,
            )
            # At-least-once: commit only after the caller finished iterating
            # to the yield point. If the caller crashes mid-processing, the
            # broker will redeliver the message and the ControlLoop's
            # idempotency_key dedupe will make the retry a no-op.
            await consumer.commit()
    finally:
        await consumer.stop()


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decode(value: bytes | None) -> Mapping[str, Any]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"_raw": value.decode("utf-8", errors="replace")}
    if not isinstance(parsed, dict):
        return {"_wrapped": parsed}
    return parsed


def _decode_key(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace")


__all__ = ["EventHubsKafkaBus", "EventHubsKafkaBusConfig"]
