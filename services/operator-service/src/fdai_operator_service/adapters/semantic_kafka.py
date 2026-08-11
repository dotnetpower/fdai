"""Managed-identity Event Hubs Kafka transport for Operator semantic turns."""

from __future__ import annotations

import asyncio
import json
import math
import re
import ssl
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.abc import AbstractTokenProvider
from azure.identity.aio import ManagedIdentityCredential

from fdai_operator_service.contract_codecs import CORE_REQUEST_PRODUCER_V12

MAX_SEMANTIC_MESSAGE_BYTES = 1_000_000
_TOPIC_PATTERN = re.compile(r"^[a-z0-9._-]+$")


class _ManagedIdentityTokenProvider(AbstractTokenProvider):  # type: ignore[misc]
    def __init__(self, credential: ManagedIdentityCredential, scope: str) -> None:
        self._credential = credential
        self._scope = scope

    async def token(self) -> str:
        token = await self._credential.get_token(self._scope)
        if not isinstance(token.token, str):
            raise RuntimeError("managed identity returned a non-string token")
        return token.token


@dataclass(frozen=True, slots=True)
class OperatorSemanticKafkaConfig:
    """Configure one bounded Kafka producer/consumer pair for semantic turns."""

    bootstrap_servers: str
    request_topic: str = "operator.semantic-turn.requests"
    projection_topic: str = "core.semantic-turn.projections"
    client_id: str = "fdai-operator-service"
    auto_offset_reset: str = "earliest"
    dlq_suffix: str = ".dlq"
    maximum_message_bytes: int = MAX_SEMANTIC_MESSAGE_BYTES

    def __post_init__(self) -> None:
        if not self.bootstrap_servers.strip():
            raise ValueError("Kafka bootstrap servers MUST NOT be empty")
        if not self.client_id.strip():
            raise ValueError("Kafka client id MUST NOT be empty")
        if (
            self.request_topic == self.projection_topic
            or _TOPIC_PATTERN.fullmatch(self.request_topic) is None
            or _TOPIC_PATTERN.fullmatch(self.projection_topic) is None
        ):
            raise ValueError("semantic Kafka topics MUST be distinct valid topic names")
        if self.auto_offset_reset not in {"earliest", "latest"}:
            raise ValueError("auto_offset_reset MUST be earliest or latest")
        if not self.dlq_suffix:
            raise ValueError("Kafka DLQ suffix MUST NOT be empty")
        if self.maximum_message_bytes < 1:
            raise ValueError("Kafka maximum message bytes MUST be positive")


class OperatorSemanticKafkaBus:
    """Publish requests and yield result mappings with commit-after-processing semantics."""

    def __init__(
        self,
        *,
        config: OperatorSemanticKafkaConfig,
        credential: ManagedIdentityCredential,
    ) -> None:
        host = config.bootstrap_servers.split(",", 1)[0].strip().split(":", 1)[0]
        if not host:
            raise ValueError("Kafka bootstrap servers MUST contain a host")
        self._config = config
        self._credential = credential
        self._scope = f"https://{host}/.default"
        self._producer: AIOKafkaProducer | None = None
        self._producer_lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        """Start the authenticated producer without publishing a record."""
        await self._get_producer()

    def readiness(self) -> bool:
        """Report validated configuration without acquiring a managed-identity token."""
        return not self._closed

    async def probe_readiness(self) -> bool:
        """Verify bounded authenticated producer startup without sending a record."""
        try:
            await asyncio.wait_for(self.start(), timeout=5.0)
        except Exception:  # noqa: BLE001 - readiness exposes no provider detail
            return False
        return True

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        """Publish one canonical bounded JSON object with a stable partition key."""
        allowed = {
            self._config.request_topic,
            f"{self._config.request_topic}{self._config.dlq_suffix}",
            f"{self._config.projection_topic}{self._config.dlq_suffix}",
        }
        if topic not in allowed:
            raise ValueError("semantic Kafka publish topic is not configured")
        producer = await self._get_producer()
        encoded = (
            CORE_REQUEST_PRODUCER_V12.encode(payload)
            if topic == self._config.request_topic
            else _encode(payload, maximum=self._config.maximum_message_bytes)
        )
        return await producer.send_and_wait(
            topic,
            key=key.encode("utf-8"),
            value=encoded,
        )

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        """Yield valid mappings and commit only after downstream processing resumes."""
        if topic != self._config.projection_topic:
            raise ValueError("semantic Kafka subscription topic is not configured")
        return self._iter_consumer(topic, group_id)

    async def close(self) -> None:
        """Stop the producer and close the owned managed-identity credential once."""
        async with self._producer_lock:
            if self._closed:
                return
            producer, self._producer = self._producer, None
            self._closed = True
            if producer is not None:
                await producer.stop()
        await self._credential.close()

    async def aclose(self) -> None:
        """Close the transport through the Operator application lifecycle contract."""
        await self.close()

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._producer_lock:
            if self._closed:
                raise RuntimeError("semantic Kafka transport is closed")
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._config.bootstrap_servers,
                    client_id=self._config.client_id,
                    security_protocol="SASL_SSL",
                    sasl_mechanism="OAUTHBEARER",
                    sasl_oauth_token_provider=_ManagedIdentityTokenProvider(
                        self._credential,
                        self._scope,
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
                    max_request_size=self._config.maximum_message_bytes,
                )
                try:
                    await producer.start()
                except BaseException:
                    await producer.stop()
                    raise
                self._producer = producer
            return self._producer

    async def _iter_consumer(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._config.bootstrap_servers,
            group_id=group_id,
            client_id=self._config.client_id,
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauth_token_provider=_ManagedIdentityTokenProvider(
                self._credential,
                self._scope,
            ),
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
            max_partition_fetch_bytes=self._config.maximum_message_bytes,
        )
        try:
            await consumer.start()
            while True:
                message = await consumer.getone()
                payload, reason = _decode(
                    message.value,
                    maximum=self._config.maximum_message_bytes,
                )
                if payload is None:
                    await self.publish(
                        f"{message.topic}{self._config.dlq_suffix}",
                        _decode_key(message.key),
                        {
                            "original_topic": message.topic,
                            "reason": reason or "invalid_event_payload",
                            "source_offset": message.offset,
                        },
                    )
                    await consumer.commit()
                    continue
                yield payload
                await consumer.commit()
        finally:
            await consumer.stop()


def _encode(payload: Mapping[str, object], *, maximum: int) -> bytes:
    canonical = _canonical_value(payload)
    try:
        encoded = json.dumps(
            canonical,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("semantic Kafka payload MUST be canonical JSON") from exc
    if len(encoded) > maximum:
        raise ValueError("semantic Kafka payload exceeds the message byte cap")
    return encoded


def _decode(value: bytes | None, *, maximum: int) -> tuple[dict[str, object] | None, str | None]:
    if value is None or len(value) > maximum:
        return None, "invalid_event_payload"
    try:
        parsed: Any = json.loads(value, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "invalid_event_payload"
    if not isinstance(parsed, dict):
        return None, "invalid_event_payload"
    try:
        canonical = _canonical_value(parsed)
    except ValueError:
        return None, "invalid_event_payload"
    return canonical, None


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("semantic Kafka payload numbers MUST be finite")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("semantic Kafka payload keys MUST be strings")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    raise ValueError("semantic Kafka payload contains a non-JSON value")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _decode_key(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


__all__ = [
    "MAX_SEMANTIC_MESSAGE_BYTES",
    "OperatorSemanticKafkaBus",
    "OperatorSemanticKafkaConfig",
]
