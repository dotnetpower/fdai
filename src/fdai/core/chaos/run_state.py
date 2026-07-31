"""Monotonic, idempotent chaos run state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class ChaosRunState(StrEnum):
    PLANNED = "planned"
    IMPACT_CHECKED = "impact_checked"
    DRY_RUN_VERIFIED = "dry_run_verified"
    APPROVED = "approved"
    INJECTING = "injecting"
    OBSERVING = "observing"
    VERIFIED = "verified"
    STOP_TRIGGERED = "stop_triggered"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    FAILED = "failed"
    DENIED = "denied"

    @property
    def terminal(self) -> bool:
        return self in {self.RECOVERED, self.ESCALATED, self.FAILED, self.DENIED}


_ALLOWED: dict[ChaosRunState, frozenset[ChaosRunState]] = {
    ChaosRunState.PLANNED: frozenset({ChaosRunState.IMPACT_CHECKED, ChaosRunState.DENIED}),
    ChaosRunState.IMPACT_CHECKED: frozenset({ChaosRunState.DRY_RUN_VERIFIED}),
    ChaosRunState.DRY_RUN_VERIFIED: frozenset({ChaosRunState.APPROVED}),
    ChaosRunState.APPROVED: frozenset({ChaosRunState.INJECTING}),
    ChaosRunState.INJECTING: frozenset(
        {ChaosRunState.OBSERVING, ChaosRunState.STOP_TRIGGERED, ChaosRunState.FAILED}
    ),
    ChaosRunState.OBSERVING: frozenset(
        {ChaosRunState.VERIFIED, ChaosRunState.STOP_TRIGGERED, ChaosRunState.FAILED}
    ),
    ChaosRunState.VERIFIED: frozenset({ChaosRunState.RECOVERING}),
    ChaosRunState.STOP_TRIGGERED: frozenset({ChaosRunState.RECOVERING}),
    ChaosRunState.RECOVERING: frozenset(
        {ChaosRunState.RECOVERED, ChaosRunState.ESCALATED, ChaosRunState.FAILED}
    ),
}


@dataclass(frozen=True, slots=True)
class ChaosRunSnapshot:
    run_id: str
    state: ChaosRunState
    revision: int
    updated_at: datetime
    last_idempotency_key: str


def transition_chaos_run(
    snapshot: ChaosRunSnapshot,
    *,
    target: ChaosRunState,
    idempotency_key: str,
    at: datetime,
) -> ChaosRunSnapshot:
    if not idempotency_key.strip() or at.tzinfo is None:
        raise ValueError("transition idempotency key and aware timestamp are required")
    if idempotency_key == snapshot.last_idempotency_key:
        return snapshot
    if snapshot.state.terminal:
        raise ValueError("terminal chaos run cannot transition")
    if target not in _ALLOWED.get(snapshot.state, frozenset()):
        raise ValueError(f"invalid chaos transition {snapshot.state.value}->{target.value}")
    if at < snapshot.updated_at:
        raise ValueError("chaos transition time MUST be monotonic")
    return replace(
        snapshot,
        state=target,
        revision=snapshot.revision + 1,
        updated_at=at,
        last_idempotency_key=idempotency_key,
    )


__all__ = ["ChaosRunSnapshot", "ChaosRunState", "transition_chaos_run"]
