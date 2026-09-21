"""Durable exact-result replay and bounded publication recovery for index events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fdai.agents import ContextIndexMessage
from fdai.shared.providers.state_store import StateStore

_PREFIX = "ontology-context-evidence:v1:"


class _Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request: ContextIndexMessage
    result: ContextIndexMessage
    revision: int = Field(strict=True, ge=1, le=2)
    state: Literal["pending", "published"] = "pending"


class OntologyIndexJournal:
    """One durable phase result doubles as its pending publication record."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def replay(self, request: ContextIndexMessage, owner: str) -> ContextIndexMessage | None:
        raw = await self._store.read_state(self._key(request, owner))
        if raw is None:
            return None
        outcome = _Outcome.model_validate(raw)
        if (
            outcome.request != request
            or outcome.result.producer_principal != owner
            or outcome.result.correlation_id != request.correlation_id
            or (outcome.state == "pending") != (outcome.revision == 1)
        ):
            raise ValueError("ontology index phase outcome identity mismatch")
        await self.immutable(
            f"{_PREFIX}message:{outcome.result.idempotency_key}",
            outcome.result.model_dump(mode="json"),
        )
        return outcome.result

    async def record(
        self,
        request: ContextIndexMessage,
        result: ContextIndexMessage,
        owner: str,
    ) -> ContextIndexMessage:
        outcome = _Outcome(request=request, result=result, revision=1)
        await self._store.write_state_if_absent(
            self._key(request, owner), outcome.model_dump(mode="json")
        )
        replay = await self.replay(request, owner)
        if replay is None:
            raise ValueError("ontology index phase outcome lost durable state")
        return replay

    async def message(self, key: str, owner: str) -> ContextIndexMessage:
        raw = await self._store.read_state(f"{_PREFIX}message:{key}")
        if raw is None:
            raise ValueError("ontology index owned message record is unavailable")
        message = ContextIndexMessage.model_validate(raw)
        if message.idempotency_key != key or message.producer_principal != owner:
            raise ValueError("ontology index owned message identity mismatch")
        return message

    async def require_message(self, message: ContextIndexMessage, owner: str) -> None:
        if await self.message(message.idempotency_key, owner) != message:
            raise ValueError("ontology index event differs from its immutable owner record")

    async def pending(self, owner: str, *, limit: int = 32) -> tuple[ContextIndexMessage, ...]:
        if owner not in {"Muninn", "Heimdall", "Saga"} or not 1 <= limit <= 64:
            raise ValueError("ontology publication recovery requires bounded owned selection")
        rows, _total = await self._store.read_state_page(
            f"{_PREFIX}{owner}:result:",
            limit=limit,
            field="state",
            value="pending",
        )
        messages: list[ContextIndexMessage] = []
        for row in rows:
            outcome = _Outcome.model_validate(row)
            result = await self.replay(outcome.request, owner)
            if result is None:
                raise ValueError("ontology pending outcome is unavailable")
            messages.append(result)
        return tuple(messages)

    async def published(self, message: ContextIndexMessage) -> None:
        await self.require_message(message, message.producer_principal)
        key = f"{_PREFIX}publication:{message.idempotency_key}"
        await self.immutable(key, {"message_key": message.idempotency_key})

    async def acknowledge_pending(self, owner: str, *, limit: int = 64) -> int:
        rows, _total = await self._store.read_state_page(
            f"{_PREFIX}{owner}:result:",
            limit=limit,
            field="state",
            value="pending",
        )
        completed = 0
        for row in rows:
            outcome = _Outcome.model_validate(row)
            acknowledgement = await self._store.read_state(
                f"{_PREFIX}publication:{outcome.result.idempotency_key}"
            )
            if acknowledgement != {"message_key": outcome.result.idempotency_key}:
                continue
            updated = outcome.model_copy(update={"state": "published", "revision": 2})
            completed += int(
                await self._store.compare_and_set_state(
                    self._key(outcome.request, owner),
                    updated.model_dump(mode="json"),
                    expected_revision=1,
                )
            )
        return completed

    async def immutable(self, key: str, value: dict[str, Any]) -> None:
        if not await self._store.write_state_if_absent(key, value):
            if await self._store.read_state(key) != value:
                raise ValueError("ontology index immutable evidence conflict")

    @staticmethod
    def _key(request: ContextIndexMessage, owner: str) -> str:
        return f"{_PREFIX}{owner}:result:{request.idempotency_key}"
