"""Durable denial journal and the single aware clock for the safeguard lifecycle.

A refusal is evidence too. Every lifecycle phase that cannot prove a safe
dispatch records the exact bounded reason here and returns a blocked result,
so a denial is never an unlogged silent no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.executor.safeguard_lifecycle_models import (
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.state_store import StateStore


class SafeguardDenialJournal:
    """Record one bounded denial reason and return the blocked result."""

    __slots__ = ("_clock", "_config", "_denial_audit_store")

    def __init__(
        self,
        *,
        config: SafeguardLifecycleCoordinatorConfig,
        denial_audit_store: StateStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._denial_audit_store = denial_audit_store
        self._clock = clock

    async def deny(
        self,
        action: Action,
        reason: str,
    ) -> SafeguardCoordinatedDispatchResult:
        bounded_reason = reason[:512]
        await self._denial_audit_store.append_audit_entry(
            {
                "event_id": str(action.event_id),
                "action_id": str(action.action_id),
                "idempotency_key": action.idempotency_key,
                "actor": self._config.actor,
                "action_kind": "executor.safeguard_lifecycle.denied",
                "audit_phase": "terminal",
                "outcome": "denied",
                "reason": bounded_reason,
                "recorded_at": self.now().isoformat(),
                "execution_authority": False,
                "effect_verified": False,
            }
        )
        return SafeguardCoordinatedDispatchResult(
            disposition=SafeguardCoordinationDisposition.BLOCKED,
            bundle_digest=None,
            lifecycle=None,
            closure_receipt=None,
            dispatch_performed=False,
            reason=bounded_reason,
        )

    def now(self) -> datetime:
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("safeguard lifecycle clock MUST return an aware datetime")
        return value.astimezone(UTC)


__all__ = ["SafeguardDenialJournal"]
