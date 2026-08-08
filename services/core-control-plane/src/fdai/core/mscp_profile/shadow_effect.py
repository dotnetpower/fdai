"""Shadow-only effect observation contracts and audit projection.

MSCP provenance: Level 3 prediction gating. The control loop calls the
prediction provider before dispatch and the independent observer after
dispatch. This module only defines collaborators and a pure audit projection;
it never performs I/O or changes the execution result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationResult,
    ExpectedEffect,
    ObservedEffect,
)
from fdai.core.mscp_profile.profile import DEFAULT_PROFILE
from fdai.shared.contracts.models import Action, Mode


class ExpectedEffectProvider(Protocol):
    """Produce a pre-dispatch expected effect for one action."""

    async def __call__(self, action: Action) -> ExpectedEffect | None: ...


class IndependentEffectObserver(Protocol):
    """Observe an effect after dispatch without receiving the executor receipt."""

    async def __call__(
        self,
        action: Action,
        expected: ExpectedEffect,
    ) -> ObservedEffect | None: ...


def build_shadow_effect_audit(
    *,
    action: Action,
    execution_outcome: str,
    verification: EffectVerificationResult,
    recorded_at: datetime,
    expected: ExpectedEffect | None = None,
    observed: ObservedEffect | None = None,
) -> dict[str, object]:
    """Build one secret-free, shadow-only effect verification audit entry."""

    entry: dict[str, object] = {
        "actor": "fdai.core.mscp_profile",
        "action_kind": "effect_verification.shadow",
        "mode": Mode.SHADOW.value,
        "action_mode": action.mode.value,
        "event_id": str(action.event_id),
        "action_id": str(action.action_id),
        "action_type": action.action_type,
        "idempotency_key": action.idempotency_key,
        "target_resource_ref": action.target_resource_ref,
        "execution_outcome": execution_outcome,
        "verification_status": verification.status.value,
        "verification_reason": verification.reason.value,
        "recorded_at": recorded_at.isoformat(),
        **DEFAULT_PROFILE.audit_context(),
    }
    if expected is not None:
        entry.update(
            {
                "prediction_id": expected.prediction_id,
                "effect_metric": expected.metric,
                "acceptable_min": expected.acceptable_min,
                "acceptable_max": expected.acceptable_max,
                "predicted_at": expected.predicted_at.isoformat(),
                "observation_deadline": expected.observation_deadline.isoformat(),
            }
        )
    if observed is not None:
        entry.update(
            {
                "observed_value": observed.value,
                "observed_at": observed.observed_at.isoformat(),
            }
        )
    return entry


__all__ = [
    "ExpectedEffectProvider",
    "IndependentEffectObserver",
    "build_shadow_effect_audit",
]
