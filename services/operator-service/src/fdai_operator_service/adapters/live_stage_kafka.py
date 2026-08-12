"""Kafka stage-topic relay for the Operator Live SSE surface."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from aiokafka import AIOKafkaConsumer
from aiokafka.abc import AbstractTokenProvider
from azure.identity.aio import ManagedIdentityCredential

from fdai_operator_service.streaming import LiveStreamHub, parse_stage_frame

_LOGGER = logging.getLogger(__name__)
_MAX_STAGE_MESSAGE_BYTES = 256 * 1_024


class _KafkaMessage(Protocol):
    value: bytes | None


class _KafkaConsumer(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def getone(self) -> _KafkaMessage: ...

    async def commit(self) -> None: ...


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
class LiveStageKafkaConfig:
    """Configure one bounded Kafka consumer for the Core stage topic."""

    bootstrap_servers: str
    stage_topic: str = "aw.pipeline.stages"
    group_id: str = "fdai-operator-live-stage-v1"
    client_id: str = "fdai-operator-live-stage"
    security_protocol: Literal["SASL_SSL", "PLAINTEXT"] = "SASL_SSL"

    def __post_init__(self) -> None:
        for label, value in (
            ("bootstrap_servers", self.bootstrap_servers),
            ("stage_topic", self.stage_topic),
            ("group_id", self.group_id),
            ("client_id", self.client_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} MUST NOT be empty")
        if self.security_protocol not in {"SASL_SSL", "PLAINTEXT"}:
            raise ValueError("security_protocol MUST be SASL_SSL or PLAINTEXT")


class LiveStageKafkaRelay:
    """Consume validated Core stage frames and fan them out to Live subscribers."""

    def __init__(
        self,
        *,
        config: LiveStageKafkaConfig,
        hub: LiveStreamHub,
        credential: ManagedIdentityCredential | None,
        consumer_factory: Callable[[], _KafkaConsumer] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if config.security_protocol == "SASL_SSL" and credential is None:
            raise ValueError("SASL_SSL Kafka transport requires a managed identity")
        self._config = config
        self._hub = hub
        self._credential = credential
        host = config.bootstrap_servers.split(",", 1)[0].split(":", 1)[0]
        self._scope = f"https://{host}/.default"
        self._consumer_factory = consumer_factory or self._build_consumer
        self._sleeper = sleeper
        self._consumer: _KafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        """Start the consumer and fail application startup if initial connection fails."""
        if self._closed:
            raise RuntimeError("Live stage relay is closed")
        if self._task is not None:
            return
        consumer = self._consumer_factory()
        try:
            await consumer.start()
        except BaseException:
            await consumer.stop()
            raise
        self._consumer = consumer
        self._task = asyncio.create_task(self._relay(consumer), name="operator-live-stage")

    def readiness(self) -> bool:
        """Report whether the configured stage consumer task remains active."""
        return self._consumer is not None and self._task is not None and not self._task.done()

    async def aclose(self) -> None:
        """Stop the relay, consumer, and its independently owned credential."""
        if self._closed:
            return
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            await consumer.stop()
        if self._credential is not None:
            await self._credential.close()

    async def _relay(self, consumer: _KafkaConsumer) -> None:
        active = consumer
        while True:
            try:
                message = await active.getone()
                event = _decode_stage_event(message.value)
                if event is not None:
                    await self._hub.publish(event)
                await active.commit()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - transient Kafka loss reconnects
                _LOGGER.warning("live_stage_consumer_retrying", exc_info=True)
                await active.stop()
                if self._consumer is active:
                    self._consumer = None
                await self._sleeper(1.0)
                active = self._consumer_factory()
                await active.start()
                self._consumer = active

    def _build_consumer(self) -> _KafkaConsumer:
        options: dict[str, object]
        if self._config.security_protocol == "PLAINTEXT":
            options = {"security_protocol": "PLAINTEXT"}
        else:
            credential = self._credential
            if credential is None:  # pragma: no cover - constructor invariant
                raise RuntimeError("managed identity credential is unavailable")
            options = {
                "security_protocol": "SASL_SSL",
                "sasl_mechanism": "OAUTHBEARER",
                "sasl_oauth_token_provider": _ManagedIdentityTokenProvider(credential, self._scope),
                "ssl_context": ssl.create_default_context(),
            }
        return cast(
            _KafkaConsumer,
            AIOKafkaConsumer(
                self._config.stage_topic,
                bootstrap_servers=self._config.bootstrap_servers,
                group_id=self._config.group_id,
                client_id=self._config.client_id,
                enable_auto_commit=False,
                auto_offset_reset="latest",
                max_partition_fetch_bytes=_MAX_STAGE_MESSAGE_BYTES,
                **options,
            ),
        )


def _decode_stage_event(value: bytes | None):  # type: ignore[no-untyped-def]
    if value is None or len(value) > _MAX_STAGE_MESSAGE_BYTES:
        return None
    try:
        payload: Any = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return parse_stage_frame(payload)


__all__ = ["LiveStageKafkaConfig", "LiveStageKafkaRelay"]
