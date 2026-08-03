"""Validated durable record codec for control-plane recovery plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai.core.verticals.resilience.recovery_plan import (
    RecoveryMode,
    RecoveryObjectives,
    RecoveryPlan,
    RecoveryProfile,
    RecoveryState,
)

_STATE_PREFIX: Final[str] = "control-plane-recovery:"
_SCHEMA_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class RecoveryPlanRecord:
    """Current plan projection plus its durable CAS metadata."""

    plan: RecoveryPlan
    storage_revision: int
    last_transition_at: datetime
    last_idempotency_key: str

    def __post_init__(self) -> None:
        if self.storage_revision < 0:
            raise ValueError("storage_revision MUST be >= 0")
        if self.last_transition_at.tzinfo is None or self.last_transition_at.utcoffset() is None:
            raise ValueError("last_transition_at MUST be timezone-aware")
        if not self.last_idempotency_key:
            raise ValueError("last_idempotency_key MUST be non-empty")


def recovery_state_key(plan_id: str) -> str:
    return f"{_STATE_PREFIX}{plan_id}"


def serialize_recovery_record(record: RecoveryPlanRecord) -> dict[str, Any]:
    plan = record.plan
    return {
        "schema_version": _SCHEMA_VERSION,
        "revision": record.storage_revision,
        "last_transition_at": recovery_utc(record.last_transition_at),
        "last_idempotency_key": record.last_idempotency_key,
        "plan": {
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "mode": plan.mode.value,
            "profile": plan.profile.value,
            "primary_region": plan.primary_region,
            "recovery_region": plan.recovery_region,
            "requester_ref": plan.requester_ref,
            "scope": list(plan.scope),
            "objectives": {
                "rpo_seconds": plan.objectives.rpo_seconds,
                "rto_seconds": plan.objectives.rto_seconds,
                "max_degraded_seconds": plan.objectives.max_degraded_seconds,
            },
            "stop_conditions": list(plan.stop_conditions),
            "rollback_ref": plan.rollback_ref,
            "max_affected_resources": plan.max_affected_resources,
            "state": plan.state.value,
            "recovery_epoch": plan.recovery_epoch,
        },
    }


def parse_recovery_record(raw: Mapping[str, Any]) -> RecoveryPlanRecord:
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported recovery record schema_version")
    plan_raw = _mapping(raw["plan"])
    objectives_raw = _mapping(plan_raw["objectives"])
    plan = RecoveryPlan(
        plan_id=_text(plan_raw["plan_id"]),
        revision=_integer(plan_raw["revision"]),
        mode=RecoveryMode(_text(plan_raw["mode"])),
        profile=RecoveryProfile(_text(plan_raw["profile"])),
        primary_region=_text(plan_raw["primary_region"]),
        recovery_region=_text(plan_raw["recovery_region"]),
        requester_ref=_text(plan_raw["requester_ref"]),
        scope=_text_tuple(plan_raw["scope"]),
        objectives=RecoveryObjectives(
            rpo_seconds=_number(objectives_raw["rpo_seconds"]),
            rto_seconds=_number(objectives_raw["rto_seconds"]),
            max_degraded_seconds=_number(objectives_raw["max_degraded_seconds"]),
        ),
        stop_conditions=_text_tuple(plan_raw["stop_conditions"]),
        rollback_ref=_text(plan_raw["rollback_ref"]),
        max_affected_resources=_integer(plan_raw["max_affected_resources"]),
        state=RecoveryState(_text(plan_raw["state"])),
        recovery_epoch=_integer(plan_raw["recovery_epoch"]),
    )
    return RecoveryPlanRecord(
        plan=plan,
        storage_revision=_integer(raw["revision"]),
        last_transition_at=_timestamp(raw["last_transition_at"]),
        last_idempotency_key=_text(raw["last_idempotency_key"]),
    )


def recovery_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("recovery record field MUST be an object")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("recovery record field MUST be a string")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("recovery record field MUST be an integer")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("recovery objective MUST be numeric")
    return float(value)


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("recovery record list MUST contain strings")
    return tuple(value)


def _timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(_text(value))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("recovery record timestamp MUST be timezone-aware")
    return timestamp
