"""Provider contracts for control-plane recovery approval and shadow actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RecoveryApprovalEvidence:
    """Bound fields an approval provider verifies before a recovery transition."""

    approval_ref: str
    actor_ref: str
    plan_id: str
    plan_revision: int
    target_state: str


@runtime_checkable
class RecoveryApprovalVerifier(Protocol):
    """Verify an authenticated approval bound to one recovery transition."""

    async def verify(self, evidence: RecoveryApprovalEvidence) -> bool:
        """Return true only when the approval is authentic and action-bound."""
        ...


class RegionalRecoveryAction(StrEnum):
    """Provider-neutral regional recovery action evaluated in shadow mode."""

    PROVISION_RECOVERY_REGION = "provision_recovery_region"
    FENCE_PRIMARY = "fence_primary"
    REPLAY_EVENTS = "replay_events"
    SHIFT_TRAFFIC = "shift_traffic"
    FAILBACK = "failback"


@dataclass(frozen=True, slots=True)
class RegionalRecoveryShadowRequest:
    """Immutable shadow request bound to one plan revision and recovery epoch."""

    action: RegionalRecoveryAction
    plan_id: str
    plan_revision: int
    recovery_epoch: int
    primary_region: str
    recovery_region: str
    scope: tuple[str, ...]
    replay_start: datetime
    replay_end: datetime


@dataclass(frozen=True, slots=True)
class RegionalRecoveryShadowReceipt:
    """Sanitized provider observation for one shadow recovery action."""

    action: RegionalRecoveryAction
    succeeded: bool
    observed_epoch: int
    primary_writer_active: bool
    recovery_writer_active: bool
    evidence_refs: tuple[str, ...]


@runtime_checkable
class RegionalRecoveryActionProvider(Protocol):
    """Evaluate regional recovery actions without applying provider effects."""

    async def evaluate_shadow(
        self,
        request: RegionalRecoveryShadowRequest,
    ) -> RegionalRecoveryShadowReceipt:
        """Return an observation-only receipt and never mutate provider state."""
        ...


__all__ = [
    "RecoveryApprovalEvidence",
    "RecoveryApprovalVerifier",
    "RegionalRecoveryAction",
    "RegionalRecoveryActionProvider",
    "RegionalRecoveryShadowReceipt",
    "RegionalRecoveryShadowRequest",
]
