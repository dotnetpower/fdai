"""Durable, separately authorized ActionType shadow-reversion writer.

This adapter can only lower an ActionType from enforce to shadow. It requires an
injected verifier for the current human authorization evidence, records intent before
mutation, rechecks the standing-authorization fence, serializes one ActionType per
command, persists the registry change, and records terminal audit. It is deliberately
unbound from runtime composition and performs no provider effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fdai.core.executor.lock import ResourceLockManager
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.shadow_reversion_command import (
    ShadowReversionCommand,
    ShadowReversionIntent,
    ShadowReversionOutcome,
    ShadowReversionTerminal,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.standing_authority import StandingAuthorizationLifecycleStore
from fdai.shared.providers.state_store import StateStore

_PREFIX = "shadow-reversion:"
_SCHEMA_VERSION = "1.0.0"


class ShadowReversionApprovalVerifier(Protocol):
    """Verify current retained human authorization for one exact command.

    The verifier owns authentication, proposer/reviewer separation evidence,
    source revision, ActionType scope, expected authorization state, safety
    bindings, and freshness. A digest match alone is insufficient.
    """

    async def verify(self, command: ShadowReversionCommand) -> bool:
        """Return true only for current, independently authenticated approval evidence."""

        ...


class PersistedShadowReversionRegistry(Protocol):
    """Minimum durable promotion-registry surface used for authority reduction."""

    def mode_of(self, action_type: str) -> Mode: ...

    def demote(self, action_type_name: str) -> object: ...

    async def refresh_for_update(self, action_type: str) -> None: ...

    async def persist(self, action_type: str) -> None: ...


class StateStoreShadowReversionWriter:
    """Apply one authorized, idempotent shadow reversion through durable stores.

    Commands are restricted to one ActionType so a successful state transition cannot
    partially apply a multi-ActionType command. A caller can submit one command per
    reviewed ActionType using the shared source revision, finding, and review evidence.
    Any verifier, fence, state, CAS, or registry failure raises and preserves or lowers
    authority; it never restores enforce mode after an uncertain demotion.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        lifecycle: StandingAuthorizationLifecycleStore,
        registry: PersistedShadowReversionRegistry,
        approvals: ShadowReversionApprovalVerifier,
    ) -> None:
        self._store = store
        self._lifecycle = lifecycle
        self._registry = registry
        self._approvals = approvals
        self._locks = ResourceLockManager()

    async def record_intent(self, intent: ShadowReversionIntent) -> bool:
        """Create or replay the exact phase-one intent atomically with audit."""

        key = _key(intent.idempotency_key)
        value = _intent_value(intent)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": "fdai.delivery.shadow_reversion",
                "action_kind": "shadow_reversion.intent_recorded",
                "command_id": intent.command_id,
                "idempotency_key": intent.idempotency_key,
                "mode": Mode.SHADOW.value,
            },
        )
        if created:
            return True
        current = await self._store.read_state(key)
        _require_intent(current, intent)
        return True

    async def current_fence_matches(self, fence: LifecycleFence) -> bool:
        """Delegate exact fence comparison to the authoritative lifecycle store."""

        return await self._lifecycle.check_fence(fence)

    async def apply(
        self,
        command: ShadowReversionCommand,
        intent: ShadowReversionIntent,
    ) -> bool:
        """Lower one approved ActionType to shadow and persist the registry state."""

        if len(command.reverted_action_types) != 1:
            raise ValueError("a durable shadow-reversion command MUST name one ActionType")
        if (
            command.command_id != intent.command_id
            or command.idempotency_key != intent.idempotency_key
        ):
            raise ValueError("shadow-reversion command does not match its recorded intent")
        action_type_id = command.reverted_action_types[0]
        action_type_name = action_type_id.partition("@")[0]
        async with self._locks.acquire(action_type_name):
            if not await self._approvals.verify(command):
                raise PermissionError("shadow-reversion approval evidence was rejected")
            if not await self._lifecycle.check_fence(command.expected_authorization):
                raise RuntimeError("standing-authorization fence changed before shadow reversion")
            key = _key(command.idempotency_key)
            current = await self._store.read_state(key)
            current = _require_intent(current, intent)
            state = str(current.get("state"))
            if state in {"applied", "terminal"}:
                return False
            if state == "intent":
                current = await self._claim(command, intent, current)
            elif state != "applying":
                raise RuntimeError("shadow-reversion state is not recoverable")
            current = _require_command(current, command)
            state = str(current.get("state"))
            if state in {"applied", "terminal"}:
                return False
            if state != "applying":
                raise RuntimeError("shadow-reversion claim did not reach applying state")
            if not await self._approvals.verify(command):
                raise PermissionError("shadow-reversion approval changed before registry mutation")
            if not await self._lifecycle.check_fence(command.expected_authorization):
                raise RuntimeError("standing-authorization fence changed before registry mutation")

            await self._registry.refresh_for_update(action_type_name)
            if self._registry.mode_of(action_type_name) is Mode.ENFORCE:
                self._registry.demote(action_type_name)
                await self._registry.persist(action_type_name)

            applied_value = {
                **dict(current),
                "state": "applied",
                "revision": _revision(current) + 1,
                "registry_mode": Mode.SHADOW.value,
            }
            applied = await self._store.compare_and_set_state_with_audit(
                key,
                applied_value,
                expected_revision=_revision(current),
                audit_entry={
                    "actor": "fdai.delivery.shadow_reversion",
                    "action_kind": "shadow_reversion.applied",
                    "command_id": command.command_id,
                    "idempotency_key": command.idempotency_key,
                    "action_type": action_type_name,
                    "mode": Mode.SHADOW.value,
                },
            )
            if not applied:
                winner = await self._store.read_state(key)
                winner = _require_command(winner, command)
                if winner.get("state") in {"applied", "terminal"}:
                    return False
                raise RuntimeError("shadow-reversion state changed during registry persistence")
            return True

    async def record_terminal(self, terminal: ShadowReversionTerminal) -> bool:
        """Atomically close the command state with its phase-two terminal audit."""

        key = _key(terminal.idempotency_key)
        current = await self._store.read_state(key)
        current = _require_terminal_identity(current, terminal)
        if current.get("state") == "terminal":
            return True
        revision = _revision(current)
        recoverable = (
            terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
            and current.get("state") == "applying"
        )
        value = {
            **dict(current),
            "state": "applying" if recoverable else "terminal",
            "revision": revision + 1,
            "last_terminal_attempt": _terminal_body(terminal),
        }
        return await self._store.compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.shadow_reversion",
                "action_kind": "shadow_reversion.terminal_recorded",
                "command_id": terminal.command_id,
                "idempotency_key": terminal.idempotency_key,
                "outcome": terminal.outcome.value,
                "mode": Mode.SHADOW.value,
            },
        )

    async def _claim(
        self,
        command: ShadowReversionCommand,
        intent: ShadowReversionIntent,
        current: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        revision = _revision(current)
        value = {
            **dict(current),
            "state": "applying",
            "revision": revision + 1,
            "command": command.audit_body(),
        }
        claimed = await self._store.compare_and_set_state_with_audit(
            _key(command.idempotency_key),
            value,
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.shadow_reversion",
                "action_kind": "shadow_reversion.claimed",
                "command_id": command.command_id,
                "idempotency_key": command.idempotency_key,
                "mode": Mode.SHADOW.value,
            },
        )
        if claimed:
            return value
        winner = await self._store.read_state(_key(intent.idempotency_key))
        return _require_intent(winner, intent)


def _key(idempotency_key: str) -> str:
    return f"{_PREFIX}{idempotency_key}"


def _fence_body(fence: LifecycleFence) -> dict[str, object]:
    return {
        "family_id": fence.family_id,
        "revision_id": fence.revision_id,
        "fencing_generation": fence.fencing_generation,
        "transition_digest": fence.transition_digest,
    }


def _intent_value(intent: ShadowReversionIntent) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "state": "intent",
        "revision": 1,
        "command_id": intent.command_id,
        "idempotency_key": intent.idempotency_key,
        "intent_digest": intent.intent_digest,
        "expected_authorization": _fence_body(intent.expected_authorization),
        "intent_recorded_at": intent.recorded_at.isoformat(),
    }


def _terminal_body(terminal: ShadowReversionTerminal) -> dict[str, object]:
    return {
        "command_id": terminal.command_id,
        "idempotency_key": terminal.idempotency_key,
        "intent_digest": terminal.intent_digest,
        "outcome": terminal.outcome.value,
        "detail": terminal.detail,
        "recorded_at": terminal.recorded_at.isoformat(),
        "execution_authority": False,
        "promotion_authority": False,
        "terminal_audit_digest": terminal.terminal_audit_digest,
    }


def _revision(value: Mapping[str, Any]) -> int:
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("shadow-reversion state revision is malformed")
    return revision


def _require_intent(
    value: Mapping[str, Any] | None,
    intent: ShadowReversionIntent,
) -> Mapping[str, Any]:
    if value is None or value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("shadow-reversion intent is missing or malformed")
    if (
        value.get("command_id") != intent.command_id
        or value.get("idempotency_key") != intent.idempotency_key
        or value.get("intent_digest") != intent.intent_digest
        or value.get("expected_authorization") != _fence_body(intent.expected_authorization)
    ):
        raise ValueError("shadow-reversion idempotency key payload conflict")
    _revision(value)
    return value


def _require_command(
    value: Mapping[str, Any] | None,
    command: ShadowReversionCommand,
) -> Mapping[str, Any]:
    if value is None or value.get("command_id") != command.command_id:
        raise ValueError("shadow-reversion command state is missing or mismatched")
    if value.get("command") != command.audit_body() and value.get("state") not in {
        "intent",
        "terminal",
    }:
        raise ValueError("shadow-reversion command payload conflict")
    _revision(value)
    return value


def _require_terminal_identity(
    value: Mapping[str, Any] | None,
    terminal: ShadowReversionTerminal,
) -> Mapping[str, Any]:
    if value is None or (
        value.get("command_id") != terminal.command_id
        or value.get("idempotency_key") != terminal.idempotency_key
        or value.get("intent_digest") != terminal.intent_digest
    ):
        raise ValueError("shadow-reversion terminal does not match its intent")
    _revision(value)
    return value


__all__ = [
    "PersistedShadowReversionRegistry",
    "ShadowReversionApprovalVerifier",
    "StateStoreShadowReversionWriter",
]
