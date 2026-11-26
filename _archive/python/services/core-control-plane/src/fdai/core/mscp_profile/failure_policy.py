"""Fail-closed bounded behavior for MSCP prediction and observation failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fdai.core.mscp_profile.effect_verification import EffectVerificationReason
from fdai.core.mscp_profile.profile_lifecycle import MscpProfileMode


class MscpFailureDisposition(StrEnum):
    """Where a failure stops relative to managed-resource dispatch."""

    HOLD_BEFORE_DISPATCH = "hold_before_dispatch"
    HOLD_AFTER_DISPATCH = "hold_after_dispatch"
    RECOVER_AFTER_DISPATCH = "recover_after_dispatch"


@dataclass(frozen=True, slots=True)
class MscpFailureDecision:
    """Bounded failure response that can only preserve or lower authority."""

    reason: EffectVerificationReason
    disposition: MscpFailureDisposition
    max_retry_attempts: int
    max_approval_requests: int
    demote_to_shadow: bool
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if not 0 <= self.max_retry_attempts <= 1:
            raise ValueError("MSCP failure retries MUST be bounded to at most one")
        if not 0 <= self.max_approval_requests <= 1:
            raise ValueError("MSCP failure approval requests MUST be bounded to at most one")
        if self.execution_authority:
            raise ValueError("MSCP failure decisions MUST NOT grant execution authority")

    def retry_allowed(self, *, attempts_used: int) -> bool:
        """Return whether one caller-owned retry remains."""

        if isinstance(attempts_used, bool) or not isinstance(attempts_used, int):
            raise ValueError("attempts_used MUST be an integer")
        if attempts_used < 0:
            raise ValueError("attempts_used MUST be non-negative")
        return attempts_used < self.max_retry_attempts

    def approval_allowed(self, *, requests_used: int) -> bool:
        """Return whether one caller-owned approval request remains."""

        if isinstance(requests_used, bool) or not isinstance(requests_used, int):
            raise ValueError("requests_used MUST be an integer")
        if requests_used < 0:
            raise ValueError("requests_used MUST be non-negative")
        return requests_used < self.max_approval_requests


_PREDICTION_FAILURES = frozenset(
    {
        EffectVerificationReason.PREDICTION_UNAVAILABLE,
        EffectVerificationReason.PREDICTION_PROVIDER_FAILED,
        EffectVerificationReason.PREDICTION_TARGET_MISMATCH,
    }
)
_RECOVERY_FAILURES = frozenset(
    {
        EffectVerificationReason.VALUE_OUTSIDE_ACCEPTABLE_RANGE,
    }
)
_OBSERVATION_FAILURES = (
    frozenset(EffectVerificationReason)
    - _PREDICTION_FAILURES
    - {
        EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE,
        *_RECOVERY_FAILURES,
    }
)


def decide_mscp_failure(
    reason: EffectVerificationReason,
    *,
    profile_mode: MscpProfileMode,
) -> MscpFailureDecision:
    """Return explicit bounded behavior for every non-success reason."""

    if reason is EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE:
        raise ValueError("successful verification is not an MSCP failure")
    demote = profile_mode is MscpProfileMode.GATING
    if reason in _PREDICTION_FAILURES:
        return MscpFailureDecision(
            reason=reason,
            disposition=MscpFailureDisposition.HOLD_BEFORE_DISPATCH,
            max_retry_attempts=1,
            max_approval_requests=1,
            demote_to_shadow=demote,
        )
    if reason in _RECOVERY_FAILURES:
        return MscpFailureDecision(
            reason=reason,
            disposition=MscpFailureDisposition.RECOVER_AFTER_DISPATCH,
            max_retry_attempts=0,
            max_approval_requests=0,
            demote_to_shadow=demote,
        )
    if reason in _OBSERVATION_FAILURES:
        return MscpFailureDecision(
            reason=reason,
            disposition=MscpFailureDisposition.HOLD_AFTER_DISPATCH,
            max_retry_attempts=0,
            max_approval_requests=0,
            demote_to_shadow=demote,
        )
    raise ValueError(f"unsupported MSCP failure reason: {reason}")


__all__ = [
    "MscpFailureDecision",
    "MscpFailureDisposition",
    "decide_mscp_failure",
]
