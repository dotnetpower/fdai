"""Isolated, revision-fenced read-index pointers with durable terminal outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.state_store import StateStore

_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_Revision = Annotated[int, Field(strict=True, ge=0)]
_PREFIX = "ontology-context-index:v1:"


class IndexScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_scope_digest: _Digest
    role: CeilingRole
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


class IndexGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: IndexScope
    manifest_digest: _Digest
    ontology_release_digest: _Digest
    source_generation: str = Field(min_length=1, max_length=256)
    source_projection_digest: _Digest
    snapshot_digest: _Digest
    vector_digest: _Digest
    generation_digest: _Digest
    validation_receipt_digest: _Digest
    embedding_space_id: str = Field(min_length=1, max_length=256)
    embedding_model_version: str = Field(min_length=1, max_length=256)
    embedding_dimension: int = Field(strict=True, ge=1, le=65536)

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


class IndexTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    command_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    scope: IndexScope
    operation: Literal["activate", "invalidate", "rollback", "retire"]
    expected_revision: _Revision
    expected_active_digest: _Digest | None
    target: IndexGeneration | None
    requested_at: AwareDatetime
    expires_at: AwareDatetime
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _closed_transition(self) -> IndexTransition:
        if not 0 < (self.expires_at - self.requested_at).total_seconds() <= 120:
            raise ValueError("index transition requires an at-most-120-second validity window")
        if (self.operation == "invalidate") != (self.target is None):
            raise ValueError("index transition target does not match its operation")
        if self.target is not None and self.target.scope != self.scope:
            raise ValueError("index transition cannot cross principal scope")
        return self

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


class IndexTerminal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: IndexTransition
    revision: _Revision
    active_digest: _Digest | None
    intent_seal_digest: _Digest
    applied_at: AwareDatetime
    producer_principal: Literal["Muninn"] = "Muninn"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _matches_command(self) -> IndexTerminal:
        expected_active = (
            self.command.expected_active_digest
            if self.command.operation == "retire"
            else self.command.target.digest
            if self.command.target is not None
            else None
        )
        if (
            self.revision != self.command.expected_revision + 1
            or self.active_digest != expected_active
            or not self.command.requested_at <= self.applied_at <= self.command.expires_at
        ):
            raise ValueError("index terminal result does not match its exact transition")
        return self


class IndexPointer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: IndexScope
    revision: _Revision = 0
    active: IndexGeneration | None = None
    retained: tuple[IndexGeneration, ...] = Field(default=(), max_length=8)
    terminal: IndexTerminal | None = None

    @model_validator(mode="after")
    def _consistent_pointer(self) -> IndexPointer:
        generations = (*self.retained, *((self.active,) if self.active is not None else ()))
        if any(item.scope != self.scope for item in generations):
            raise ValueError("index pointer generation scope mismatch")
        if len({item.digest for item in generations}) != len(generations):
            raise ValueError("index pointer repeats a generation")
        if len({item.snapshot_digest for item in generations}) != len(generations):
            raise ValueError("index pointer repeats a source snapshot")
        if self.terminal is None:
            if self.revision or generations:
                raise ValueError("index pointer lacks its terminal outcome")
        elif (
            self.terminal.revision != self.revision
            or self.terminal.command.scope != self.scope
            or self.terminal.command.expected_revision + 1 != self.revision
            or self.terminal.active_digest != (self.active.digest if self.active else None)
        ):
            raise ValueError("index pointer terminal identity mismatch")
        return self


class OntologyIndexLifecycle:
    """Mechanical Muninn persistence, requiring independently verified admission.

    ``admit`` must resolve a durable Saga intent seal and independently validated
    current target from the event-owned evidence path. Missing admission stops
    before CAS. This primitive alone does not bind agents or activate production.
    The pointer and terminal result are one atomic value. A write-through outcome
    archive is recovered before a successor can overwrite the previous terminal.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        admit: Callable[[IndexTransition], Awaitable[str | None]],
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._admit, self._clock = store, admit, clock

    async def read(self, scope: IndexScope) -> IndexPointer:
        raw = await self._store.read_state(f"{_PREFIX}{scope.digest}:pointer")
        if raw is None:
            return IndexPointer(scope=scope)
        try:
            pointer = IndexPointer.model_validate(raw)
            if pointer.scope != scope:
                raise ValueError("invalid scope")
            return pointer
        except (TypeError, ValueError):
            raise ValueError("ontology index pointer failed identity validation") from None

    async def apply(self, command: IndexTransition) -> IndexTerminal:
        """Apply an exact admitted transition once; conflicts leave prior state intact."""
        command = IndexTransition.model_validate_json(command.model_dump_json())
        async with asyncio.timeout(5):
            existing = await self._result(command)
            if existing is not None:
                return existing
            pointer = await self.read(command.scope)
            if pointer.terminal is not None:
                await self._archive(pointer.terminal)
                if pointer.terminal.command.command_id == command.command_id:
                    return self._exact_result(pointer.terminal, command)
            if pointer.revision != command.expected_revision or command.expected_active_digest != (
                pointer.active.digest if pointer.active else None
            ):
                raise ValueError("ontology index transition has a stale prior identity")
            now = self._clock()
            if now.tzinfo is None or not command.requested_at <= now <= command.expires_at:
                raise ValueError("ontology index transition expired or lacks trusted time")
            seal = await self._admit(command)
            if seal is None:
                raise ValueError(
                    "ontology index independent validation or Saga intent is unavailable"
                )
            if command.operation == "activate" and command.target is not None:
                if await self._store.read_state(_retired_key(command.target)) is not None:
                    raise ValueError("ontology index cannot reactivate a retired generation")
            active, retained = _next_generations(pointer, command)
            applied_at = self._clock()
            if applied_at.tzinfo is None or applied_at < now or applied_at > command.expires_at:
                raise ValueError("ontology index transition expired during admission")
            terminal = IndexTerminal(
                command=command,
                revision=pointer.revision + 1,
                active_digest=active.digest if active else None,
                intent_seal_digest=seal,
                applied_at=applied_at,
            )
            next_pointer = IndexPointer(
                scope=command.scope,
                revision=terminal.revision,
                active=active,
                retained=retained,
                terminal=terminal,
            )
            if pointer.revision == 0:
                await self._store.write_state_if_absent(
                    f"{_PREFIX}{command.scope.digest}:pointer",
                    pointer.model_dump(mode="json"),
                )
            if not await self._store.compare_and_set_state(
                f"{_PREFIX}{command.scope.digest}:pointer",
                next_pointer.model_dump(mode="json"),
                expected_revision=command.expected_revision,
            ):
                raced = await self._result(command)
                current = await self.read(command.scope)
                if raced is not None:
                    return raced
                if (
                    current.terminal is not None
                    and current.terminal.command.command_id == command.command_id
                ):
                    await self._archive(current.terminal)
                    return self._exact_result(current.terminal, command)
                raise ValueError("ontology index transition lost its revision fence")
            await self._archive(terminal)
            return terminal

    async def _result(self, command: IndexTransition) -> IndexTerminal | None:
        raw = await self._store.read_state(_result_key(command))
        if raw is None:
            return None
        try:
            result = IndexTerminal.model_validate(raw)
        except (TypeError, ValueError):
            raise ValueError("ontology index terminal result failed validation") from None
        return self._exact_result(result, command)

    def _exact_result(self, result: IndexTerminal, command: IndexTransition) -> IndexTerminal:
        if result.command.digest != command.digest:
            raise ValueError("ontology index command identity was reused with different content")
        return result

    async def _archive(self, result: IndexTerminal) -> None:
        if result.command.operation == "retire" and result.command.target is not None:
            retirement_key = _retired_key(result.command.target)
            retirement = {
                "snapshot_digest": result.command.target.snapshot_digest,
                "command_digest": result.command.digest,
            }
            if not await self._store.write_state_if_absent(retirement_key, retirement):
                if await self._store.read_state(retirement_key) != retirement:
                    raise ValueError("ontology index retirement identity conflict")
        key = _result_key(result.command)
        value = result.model_dump(mode="json")
        if not await self._store.write_state_if_absent(key, value):
            if await self._store.read_state(key) != value:
                raise ValueError("ontology index terminal archive conflict")


def _result_key(command: IndexTransition) -> str:
    return f"{_PREFIX}{command.scope.digest}:result:{content_digest(command.command_id)}"


def _retired_key(generation: IndexGeneration) -> str:
    return f"{_PREFIX}{generation.scope.digest}:retired:{generation.snapshot_digest}"


def _next_generations(
    pointer: IndexPointer,
    command: IndexTransition,
) -> tuple[IndexGeneration | None, tuple[IndexGeneration, ...]]:
    retained = list(pointer.retained)
    target = command.target
    if command.operation == "retire":
        if target not in retained:
            raise ValueError("ontology index can retire only a retained inactive generation")
        retained.remove(target)
        return pointer.active, tuple(retained)
    if command.operation == "rollback":
        if target not in retained:
            raise ValueError("ontology index rollback requires a retained exact generation")
        retained.remove(target)
    elif command.operation == "activate" and (target == pointer.active or target in retained):
        raise ValueError("ontology index activation requires a new generation")
    if pointer.active is not None:
        retained.append(pointer.active)
    if len(retained) > 8:
        raise ValueError("ontology index retention capacity requires explicit retirement")
    return target, tuple(retained)
