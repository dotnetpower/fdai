"""Owner-checked ContextIndex choreography over the existing Pantheon topics."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import Agent
from .bus import Handler

_LOG = logging.getLogger(__name__)

IndexPhase = Literal[
    "prepare",
    "prepared",
    "validated",
    "intent",
    "intent_sealed",
    "terminal",
    "terminal_sealed",
    "ready",
    "transition",
    "transition_prepared",
    "transition_validated",
]
_OWNERS: dict[str, str] = {
    "transition": "Huginn",
    "transition_prepared": "Muninn",
    "transition_validated": "Heimdall",
    "prepare": "Huginn",
    "prepared": "Muninn",
    "validated": "Heimdall",
    "intent": "Muninn",
    "intent_sealed": "Saga",
    "terminal": "Muninn",
    "terminal_sealed": "Saga",
    "ready": "Muninn",
}
_TOPICS: dict[str, str] = {
    "transition": "object.event",
    "transition_prepared": "object.context-index",
    "transition_validated": "object.retrieval-validation",
    "prepare": "object.event",
    "prepared": "object.context-index",
    "validated": "object.retrieval-validation",
    "intent": "object.context-index",
    "intent_sealed": "object.audit-entry",
    "terminal": "object.context-index",
    "terminal_sealed": "object.audit-entry",
    "ready": "object.context-index",
}
_NEXT: dict[str, tuple[str, IndexPhase]] = {
    "transition": ("Muninn", "transition_prepared"),
    "transition_prepared": ("Heimdall", "transition_validated"),
    "transition_validated": ("Muninn", "intent"),
    "prepare": ("Muninn", "prepared"),
    "prepared": ("Heimdall", "validated"),
    "validated": ("Muninn", "intent"),
    "intent": ("Saga", "intent_sealed"),
    "intent_sealed": ("Muninn", "terminal"),
    "terminal": ("Saga", "terminal_sealed"),
    "terminal_sealed": ("Muninn", "ready"),
}


class ContextIndexMessage(BaseModel):
    """Closed content-bound envelope; each mechanical worker also validates its body."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    envelope_schema_version: Literal[1] = 1
    kind: Literal["ontology_context_index"] = "ontology_context_index"
    event_type: Literal["ontology.context_index.v1"] = "ontology.context_index.v1"
    phase: IndexPhase
    producer_principal: str
    correlation_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    body: dict[str, Any]
    idempotency_key: str = Field(pattern=r"^ontology-context-index:sha256:[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _owner_and_content(self) -> ContextIndexMessage:
        if self.producer_principal != _OWNERS[self.phase]:
            raise ValueError("ontology ContextIndex phase has the wrong publishing owner")
        encoded = _canonical_body_bytes(self.body)
        if len(encoded) > 262_144:
            raise ValueError("ontology ContextIndex body exceeds its byte bound")
        content_key = _content_key(
            phase=self.phase,
            producer_principal=self.producer_principal,
            correlation_id=self.correlation_id,
            body=self.body,
            body_bytes=encoded,
        )
        if self.idempotency_key != content_key:
            raise ValueError("ontology ContextIndex message content identity mismatch")
        return self

    @property
    def topic(self) -> str:
        return _TOPICS[self.phase]

    @property
    def content_key(self) -> str:
        body_bytes = _canonical_body_bytes(self.body)
        return _content_key(
            phase=self.phase,
            producer_principal=self.producer_principal,
            correlation_id=self.correlation_id,
            body=self.body,
            body_bytes=body_bytes,
        )

    @classmethod
    def create(
        cls,
        *,
        phase: IndexPhase,
        correlation_id: str,
        body: dict[str, Any],
    ) -> ContextIndexMessage:
        owner = _OWNERS[phase]
        body_bytes = _canonical_body_bytes(body)
        key = _content_key(
            phase=phase,
            producer_principal=owner,
            correlation_id=correlation_id,
            body=body,
            body_bytes=body_bytes,
        )
        return cls(
            phase=phase,
            producer_principal=owner,
            correlation_id=correlation_id,
            body=body,
            idempotency_key=key,
        )


ContextIndexHandler = Callable[[ContextIndexMessage], Awaitable[ContextIndexMessage]]


@dataclass(frozen=True, slots=True)
class ContextIndexWorkerBindings:
    """Separate mechanical handlers; agents retain publication and ownership."""

    muninn: ContextIndexHandler
    heimdall: ContextIndexHandler
    saga: ContextIndexHandler
    published: Callable[[ContextIndexMessage], Awaitable[None]] | None = None
    pending: Callable[[str], Awaitable[tuple[ContextIndexMessage, ...]]] | None = None


def owned_context_index_handler(
    agent: Agent,
    bindings: ContextIndexWorkerBindings | None,
    fallback: Handler,
) -> Handler:
    """Route only the exact owned phase and prevent cross-family fallback effects."""

    async def handle(topic: str, payload: dict[str, Any]) -> None:
        if payload.get("kind") != "ontology_context_index":
            await fallback(topic, payload)
            return
        message = ContextIndexMessage.model_validate(payload)
        if topic != message.topic:
            raise ValueError("ontology ContextIndex message arrived on the wrong owned topic")
        if agent.spec.name == "Saga":
            if not getattr(agent, "durable_audit", False):
                raise RuntimeError("ontology ContextIndex requires durable Saga audit")
            await fallback(topic, payload)
        next_step = _NEXT.get(message.phase)
        if next_step is None or next_step[0] != agent.spec.name:
            return
        if bindings is None or agent.bus is None:
            raise RuntimeError("ontology ContextIndex owner binding is unavailable")
        callbacks = {
            "Muninn": bindings.muninn,
            "Heimdall": bindings.heimdall,
            "Saga": bindings.saga,
        }
        async with asyncio.timeout(120):
            result = await callbacks[agent.spec.name](message)
        result = ContextIndexMessage.model_validate(result)
        if (
            result.phase != next_step[1]
            or result.producer_principal != agent.spec.name
            or result.correlation_id != message.correlation_id
        ):
            raise ValueError("ontology ContextIndex worker crossed its owned transition")
        await agent.bus.publish(agent.spec.name, result.topic, result.model_dump(mode="json"))
        if bindings.published is not None:
            try:
                await bindings.published(result)
            except Exception as exc:  # noqa: BLE001 - ack failure must not duplicate publish
                _LOG.warning(
                    "ontology_context_index_publish_ack_failed",
                    extra={
                        "owner": agent.spec.name,
                        "phase": result.phase,
                        "error_type": type(exc).__name__,
                    },
                )

    return handle


async def recover_context_index_publications(
    agents: dict[str, Agent],
    bindings: ContextIndexWorkerBindings,
) -> int:
    """Republish one bounded immutable pending batch per available publishing owner."""
    if bindings.pending is None or bindings.published is None:
        return 0
    published = 0
    async with asyncio.timeout(10):
        for owner in ("Muninn", "Heimdall", "Saga"):
            agent = agents.get(owner)
            if agent is None or agent.bus is None:
                continue
            if owner == "Saga" and not getattr(agent, "durable_audit", False):
                raise RuntimeError("ontology ContextIndex recovery requires durable Saga audit")
            pending = await bindings.pending(owner)
            if len(pending) > 64:
                raise ValueError("ontology ContextIndex recovery batch exceeds its bound")
            for message in pending:
                message = ContextIndexMessage.model_validate(message)
                if message.producer_principal != owner:
                    raise ValueError("ontology ContextIndex recovery crossed publishing ownership")
                await agent.bus.publish(owner, message.topic, message.model_dump(mode="json"))
                try:
                    await bindings.published(message)
                except Exception as exc:  # noqa: BLE001 - ack failure must not duplicate publish
                    _LOG.warning(
                        "ontology_context_index_recovery_ack_failed",
                        extra={
                            "owner": owner,
                            "phase": message.phase,
                            "error_type": type(exc).__name__,
                        },
                    )
                published += 1
    return published


def _canonical_body_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(
        body,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _content_key(
    *,
    phase: str,
    producer_principal: str,
    correlation_id: str,
    body: dict[str, Any],
    body_bytes: bytes,
) -> str:
    prefix = (
        b'{"body":'
        + body_bytes
        + b',"correlation_id":'
        + json.dumps(correlation_id, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        + b',"phase":'
        + json.dumps(phase, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        + b',"producer_principal":'
        + json.dumps(producer_principal, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        + b"}"
    )
    del body
    return "ontology-context-index:sha256:" + hashlib.sha256(prefix).hexdigest()
