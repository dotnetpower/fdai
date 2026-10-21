"""Validated evaluation observations and bounded, illustrative detection policy."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from fdai.shared.contracts.models import ContractBase, Event
from pydantic import Field, field_validator, model_validator

Percent = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Counter = Annotated[int, Field(strict=True, ge=0)]
EvidenceOrigin = Literal["synthetic_replay", "authenticated_live_observation"]


class GpuSample(ContractBase):
    source: Literal["azure_monitor", "datadog", "azure_vm_run_command"]
    resource_ref: Annotated[str, Field(pattern=r"^resource:[A-Za-z0-9_.:-]{1,120}$")]
    gpu_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,120}$")]
    model: Annotated[str, Field(min_length=1, max_length=120)]
    observed_at: datetime
    utilization_pct: Percent | None = None
    memory_used_mib: Nonnegative | None = None
    memory_total_mib: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] | None = None
    temperature_c: Nonnegative | None = None
    allocated: Annotated[bool, Field(strict=True)] | None = None
    queue_depth: Counter | None = None
    xid_code: Counter | None = None
    ecc_uncorrectable_total: Counter | None = None
    cuda_oom_total: Counter | None = None
    thermal_throttled: Annotated[bool, Field(strict=True)] | None = None

    @field_validator("observed_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            self.memory_used_mib is not None
            and self.memory_total_mib is not None
            and self.memory_used_mib > self.memory_total_mib
        ):
            raise ValueError("memory used MUST NOT exceed capacity")
        return self

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.source, self.resource_ref, self.gpu_id, self.model


@dataclass(frozen=True, slots=True)
class Policy:
    """Example thresholds, not universal GPU limits or production SLOs."""

    window_seconds: int = 300
    max_gap_seconds: int = 60
    max_age_seconds: int = 120
    max_samples: int = 1_000
    saturation_pct: float = 95.0
    idle_utilization_pct: float = 5.0
    memory_pressure_pct: float = 95.0
    temperature_c: float = 85.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{field.name} MUST be a finite number")
        for name in ("window_seconds", "max_gap_seconds", "max_age_seconds", "max_samples"):
            value = getattr(self, name)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} MUST be a positive integer")
        if self.max_samples > 10_000:
            raise ValueError("max_samples MUST NOT exceed 10000")
        if self.max_gap_seconds > self.window_seconds:
            raise ValueError("max_gap_seconds MUST NOT exceed window_seconds")
        for name in ("saturation_pct", "idle_utilization_pct", "memory_pressure_pct"):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} MUST be between 0 and 100")
        if self.idle_utilization_pct >= self.saturation_pct or self.temperature_c <= 0:
            raise ValueError("policy thresholds MUST define a valid interval")


@dataclass(frozen=True, slots=True)
class Analysis:
    status: Literal["healthy", "finding", "insufficient_evidence"]
    reason: str
    samples: tuple[GpuSample, ...]
    events: tuple[Event, ...] = ()
    evidence_digest: str | None = None
    policy_digest: str | None = None
    evidence_origin: EvidenceOrigin = "synthetic_replay"
