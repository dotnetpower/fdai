"""Durable denial journal and the single aware clock for the safeguard lifecycle.

A refusal is evidence too. Every lifecycle phase that cannot prove a safe
dispatch records the exact bounded reason here and returns a blocked result,
so a denial is never an unlogged silent no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.executor.safeguard_evidence_lifecycle import SafeguardEvidenceLifecycleResult
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
        bounded_reason = await self._record(
            action=action,
            action_kind="executor.safeguard_lifecycle.denied",
            outcome="denied",
            reason=reason,
            bundle_digest=None,
            dispatch_performed=False,
        )
        return SafeguardCoordinatedDispatchResult(
            disposition=SafeguardCoordinationDisposition.BLOCKED,
            bundle_digest=None,
            lifecycle=None,
            closure_receipt=None,
            dispatch_performed=False,
            reason=bounded_reason,
        )

    async def quarantine(
        self,
        action: Action,
        *,
        reason: str,
        bundle_digest: str,
        lifecycle: SafeguardEvidenceLifecycleResult | None = None,
        dispatch_performed: bool = True,
    ) -> SafeguardCoordinatedDispatchResult:
        """Record an unknown post-dispatch outcome without permitting replay."""

        bounded_reason = await self._record(
            action=action,
            action_kind="executor.safeguard_lifecycle.quarantined",
            outcome="unknown",
            reason=reason,
            bundle_digest=bundle_digest,
            dispatch_performed=dispatch_performed,
        )
        return SafeguardCoordinatedDispatchResult(
            disposition=(
                SafeguardCoordinationDisposition.QUARANTINED
                if dispatch_performed
                else SafeguardCoordinationDisposition.BLOCKED
            ),
            bundle_digest=bundle_digest,
            lifecycle=lifecycle,
            closure_receipt=None,
            dispatch_performed=dispatch_performed,
            reason=bounded_reason,
        )

    async def record_quarantine(
        self,
        action: Action,
        *,
        reason: str,
        bundle_digest: str,
        dispatch_performed: bool = True,
    ) -> None:
        """Persist a post-dispatch quarantine before propagating cancellation."""

        await self._record(
            action=action,
            action_kind="executor.safeguard_lifecycle.quarantined",
            outcome="unknown",
            reason=reason,
            bundle_digest=bundle_digest,
            dispatch_performed=dispatch_performed,
        )

    async def _record(
        self,
        *,
        action: Action,
        action_kind: str,
        outcome: str,
        reason: str,
        bundle_digest: str | None,
        dispatch_performed: bool,
    ) -> str:
        bounded_reason = reason[:512]
        entry: dict[str, object] = {
            "event_id": str(action.event_id),
            "action_id": str(action.action_id),
            "idempotency_key": action.idempotency_key,
            "actor": self._config.actor,
            "action_kind": action_kind,
            "audit_phase": "terminal",
            "mode": action.mode.value,
            "outcome": outcome,
            "reason": bounded_reason,
            "recorded_at": self.now().isoformat(),
            "execution_authority": False,
            "effect_verified": False,
        }
        if bundle_digest is not None:
            entry["safeguard_bundle_digest"] = bundle_digest
            entry["dispatch_performed"] = dispatch_performed
        await self._denial_audit_store.append_audit_entry(entry)
        return bounded_reason

    def now(self) -> datetime:
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("safeguard lifecycle clock MUST return an aware datetime")
        return value.astimezone(UTC)


__all__ = ["SafeguardDenialJournal"]
