"""Shared records for Loki runtime mixins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ChaosProposal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    accepted: bool
    reason: str
    requested_target_count: int = 0
    targets_truncated: bool = False
    causal_hypothesis_ref: str = ""
    impact_envelope_id: str = ""
    recovery_plan_id: str = ""


@dataclass(frozen=True, slots=True)
class _Reservation:
    action_type: str
    targets: tuple[str, ...]
    reserved_at: datetime


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Loki observed_at MUST be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Loki observed_at MUST be timezone-aware")
    return parsed.astimezone(UTC)
