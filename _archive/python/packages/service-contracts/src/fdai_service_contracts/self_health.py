"""Authority-neutral FDAI self-health and operational-state projections."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest


class SelfHealthSignalName(StrEnum):
    LIVENESS_PROBE = "liveness_probe"
    READINESS_PROBE = "readiness_probe"
    ADAPTER_HEALTHCHECK = "adapter_healthcheck"
    EVENT_LAG = "event_lag"
    DLQ_DEPTH = "dlq_depth"
    COLD_START_RATE = "cold_start_rate"
    COLD_START_DURATION = "cold_start_duration"
    VERIFIER_FAILURE_RATE = "verifier_failure_rate"
    MIXED_MODEL_DISAGREEMENT_RATE = "mixed_model_disagreement_rate"
    ROLLBACK_RATE = "rollback_rate"
    OVERRIDE_RATE = "override_rate"
    DISCOVERY_LOOP_PASS_RATE = "discovery_loop_pass_rate"
    KILL_SWITCH_STATE = "kill_switch_state"
    CANARY_RESULT = "canary_result"
    TIME_SINCE_LAST_SUCCESSFUL_CANARY = "time_since_last_successful_canary"


class SelfHealthSignalStatus(StrEnum):
    HEALTHY = "healthy"
    ALERT = "alert"
    UNAVAILABLE = "unavailable"


class OperationalStateFieldName(StrEnum):
    VERSION = "version"
    CONFIGURATION = "configuration"
    RULE_EFFECT = "rule_effect"
    OVERRIDE = "override"
    DISCOVERY = "discovery"
    CANARY = "canary"
    KILL_SWITCH = "kill_switch"
    BREAK_GLASS = "break_glass"


class OperationalStateFieldStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SelfHealthSignalStateV1(ContractBase):
    """One source-qualified signal state without raw provider payloads."""

    signal: SelfHealthSignalName
    metric: Annotated[str, Field(min_length=1, max_length=256)]
    exporter_id: Annotated[str, Field(min_length=1, max_length=256)]
    status: SelfHealthSignalStatus
    value: Decimal | None = None
    observed_at: datetime | None = None
    recorded_at: datetime
    maximum_age_seconds: Annotated[int, Field(ge=1, le=86_400)]
    fresh: bool
    reason: Annotated[str, Field(min_length=1, max_length=128)]
    route: Annotated[str, Field(min_length=1, max_length=128)]
    fallback: Annotated[str, Field(min_length=1, max_length=128)]
    alert: bool
    execution_authority: Literal[False] = False

    @field_validator("metric", "exporter_id", "reason", "route", "fallback", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("self-health state text MUST be exact")
        return value

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def _aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value, "self-health state time")

    @model_validator(mode="after")
    def _status_shape(self) -> Self:
        unavailable = self.status is SelfHealthSignalStatus.UNAVAILABLE
        missing_observation = self.value is None and self.observed_at is None
        partial_observation = (self.value is None) != (self.observed_at is None)
        if partial_observation or unavailable != missing_observation:
            raise ValueError("self-health unavailable state shape is invalid")
        if unavailable and not self.alert:
            raise ValueError("self-health unavailable state MUST alert")
        if unavailable and self.fresh:
            raise ValueError("self-health unavailable state MUST NOT be fresh")
        if (self.status is SelfHealthSignalStatus.HEALTHY and self.alert) or (
            self.status in {SelfHealthSignalStatus.ALERT, SelfHealthSignalStatus.UNAVAILABLE}
            and not self.alert
        ):
            raise ValueError("self-health status and alert flag disagree")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("self-health state value MUST be finite")
        return self


class SelfHealthSnapshotV1(ContractBase):
    """Complete current state of every required self-health signal."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    catalog_version: Annotated[int, Field(ge=1)]
    generated_at: datetime
    signals: Annotated[tuple[SelfHealthSignalStateV1, ...], Field(min_length=15, max_length=15)]
    snapshot_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("generated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "self-health snapshot time")

    @model_validator(mode="after")
    def _complete_snapshot(self) -> Self:
        names = tuple(item.signal for item in self.signals)
        if names != tuple(sorted(SelfHealthSignalName, key=lambda item: item.value)):
            raise ValueError("self-health snapshot MUST contain every signal in order")
        for item in self.signals:
            if item.recorded_at != self.generated_at:
                raise ValueError("self-health signal recording time mismatch")
            if item.observed_at is None:
                continue
            age = (self.generated_at - item.observed_at).total_seconds()
            expected_fresh = 0 <= age <= item.maximum_age_seconds
            if item.fresh is not expected_fresh:
                raise ValueError("self-health signal freshness mismatch")
        expected = self_health_snapshot_digest(
            catalog_version=self.catalog_version,
            generated_at=self.generated_at,
            signals=self.signals,
        )
        if self.snapshot_digest != expected:
            raise ValueError("self-health snapshot digest mismatch")
        return self


class OperationalStateFieldV1(ContractBase):
    """One sanitized current operational-state field."""

    name: OperationalStateFieldName
    status: OperationalStateFieldStatus
    value_digest: Digest | None = None
    source: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime | None = None
    maximum_age_seconds: Annotated[int, Field(ge=1, le=86_400)]
    fresh: bool
    reason: Annotated[str, Field(min_length=1, max_length=128)]
    execution_authority: Literal[False] = False

    @field_validator("source", "reason", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("operational state text MUST be exact")
        return value

    @field_validator("observed_at")
    @classmethod
    def _aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value, "operational state observation time")

    @model_validator(mode="after")
    def _status_shape(self) -> Self:
        unavailable = self.status is OperationalStateFieldStatus.UNAVAILABLE
        missing_observation = self.value_digest is None and self.observed_at is None
        partial_observation = (self.value_digest is None) != (self.observed_at is None)
        if partial_observation or unavailable != missing_observation:
            raise ValueError("operational state availability shape is invalid")
        if unavailable and self.fresh:
            raise ValueError("unavailable operational state MUST NOT be fresh")
        return self


class OperationalStateSnapshotV1(ContractBase):
    """Complete sanitized state exposed only through an authorized read route."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: datetime
    self_health: SelfHealthSnapshotV1
    fields: Annotated[tuple[OperationalStateFieldV1, ...], Field(min_length=8, max_length=8)]
    snapshot_digest: Digest
    approval_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("generated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value, "operational state snapshot time")

    @model_validator(mode="after")
    def _complete_snapshot(self) -> Self:
        names = tuple(item.name for item in self.fields)
        if names != tuple(sorted(OperationalStateFieldName, key=lambda item: item.value)):
            raise ValueError("operational state snapshot MUST contain every field in order")
        if self.self_health.generated_at != self.generated_at:
            raise ValueError("operational and self-health snapshot times MUST match")
        for item in self.fields:
            if item.observed_at is None:
                continue
            age = (self.generated_at - item.observed_at).total_seconds()
            expected_fresh = 0 <= age <= item.maximum_age_seconds
            if item.fresh is not expected_fresh:
                raise ValueError("operational state field freshness mismatch")
        expected = operational_state_snapshot_digest(
            generated_at=self.generated_at,
            self_health=self.self_health,
            fields=self.fields,
        )
        if self.snapshot_digest != expected:
            raise ValueError("operational state snapshot digest mismatch")
        return self


def self_health_snapshot_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def operational_state_snapshot_digest(**values: object) -> str:
    return canonical_digest(_json_values(values))


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} MUST include a timezone")
    return value.astimezone(UTC)


def _json_values(values: object) -> object:
    if isinstance(values, dict):
        return {key: _json_values(value) for key, value in values.items()}
    if isinstance(values, ContractBase):
        return values.model_dump(mode="json")
    if isinstance(values, datetime):
        return _utc(values, "operational state digest time").isoformat()
    if isinstance(values, StrEnum):
        return values.value
    if isinstance(values, tuple):
        return [_json_values(value) for value in values]
    return values


__all__ = [
    "OperationalStateFieldName",
    "OperationalStateFieldStatus",
    "OperationalStateFieldV1",
    "OperationalStateSnapshotV1",
    "SelfHealthSignalName",
    "SelfHealthSignalStateV1",
    "SelfHealthSignalStatus",
    "SelfHealthSnapshotV1",
    "operational_state_snapshot_digest",
    "self_health_snapshot_digest",
]
