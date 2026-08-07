"""Event Hubs Kafka-wire publisher owned by the ingestion API."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import (
    AdapterReadiness,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)


class _ManagedIdentityTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    def __init__(self, credential: ManagedIdentityCredential, scope: str) -> None:
        self._credential = credential
        self._scope = scope

    async def token(self) -> str:
        value = (await self._credential.get_token(self._scope)).token
        if not isinstance(value, str):
            raise RuntimeError("managed identity returned a non-string token")
        return value


class EventHubsKafkaPublisher:
    """Publish idempotent JSON records through the Event Hubs Kafka endpoint."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        credential: ManagedIdentityCredential,
        client_id: str = "fdai-ingestion-api",
    ) -> None:
        if not bootstrap_servers:
            raise ValueError("Kafka bootstrap servers MUST NOT be empty")
        host = bootstrap_servers.split(",", 1)[0].strip().split(":", 1)[0]
        self._bootstrap_servers = bootstrap_servers
        self._credential = credential
        self._client_id = client_id
        self._scope = f"https://{host}/.default"
        self._producer: AIOKafkaProducer | None = None
        self._lock = asyncio.Lock()

    def readiness(self) -> AdapterReadiness:
        """Report validated Kafka composition without requesting an Azure token."""
        return configured_readiness("event-hubs-kafka-publisher")

    async def probe_readiness(self) -> AdapterReadiness:
        """Start the authenticated producer without publishing an event."""
        adapter = "event-hubs-kafka-publisher"
        try:
            await asyncio.wait_for(self._get_producer(), timeout=5.0)
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        producer = await self._get_producer()
        return await producer.send_and_wait(
            topic,
            key=key.encode("utf-8"),
            value=json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode(),
        )

    async def close(self) -> None:
        async with self._lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None
        await self._credential.close()

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._bootstrap_servers,
                    client_id=self._client_id,
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
                    await _stop(producer)
                    raise
                self._producer = producer
            return self._producer


async def _stop(client: Any) -> None:
    try:
        await client.stop()
    except BaseException:
        return
