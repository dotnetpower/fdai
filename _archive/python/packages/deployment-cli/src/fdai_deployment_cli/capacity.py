"""Deterministic workload-derived model capacity planning."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkloadEnvelope:
    """Peak model demand and approved operating headroom."""

    requests_per_minute: int
    input_tokens_per_request: int
    output_tokens_per_request: int
    concurrent_requests: int
    utilization_ceiling: float = 0.70
    quota_reserve: float = 0.20
    provider_unit_tpm: int = 1_000

    def __post_init__(self) -> None:
        for field_name in (
            "requests_per_minute",
            "input_tokens_per_request",
            "output_tokens_per_request",
            "concurrent_requests",
            "provider_unit_tpm",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} MUST be positive")
        if (
            isinstance(self.utilization_ceiling, bool)
            or not math.isfinite(self.utilization_ceiling)
            or not 0 < self.utilization_ceiling <= 1
        ):
            raise ValueError("utilization_ceiling MUST be in (0, 1]")
        if (
            isinstance(self.quota_reserve, bool)
            or not math.isfinite(self.quota_reserve)
            or not 0 <= self.quota_reserve < 1
        ):
            raise ValueError("quota_reserve MUST be in [0, 1)")

    @property
    def minimum_tpm(self) -> int:
        """Return peak token demand rounded up to the provider allocation unit."""

        tokens = self.input_tokens_per_request + self.output_tokens_per_request
        raw = math.ceil(self.requests_per_minute * tokens / self.utilization_ceiling)
        return math.ceil(raw / self.provider_unit_tpm) * self.provider_unit_tpm


@dataclass(frozen=True, slots=True)
class CapabilityDemand:
    """One required or optional model capability."""

    capability: str
    deployment_key: str
    required: bool
    envelope: WorkloadEnvelope

    def __post_init__(self) -> None:
        if not self.capability.strip() or not self.deployment_key.strip():
            raise ValueError("capability and deployment_key MUST be non-empty")


@dataclass(frozen=True, slots=True)
class DeploymentCapacity:
    """Aggregate TPM needed by capabilities sharing one approved deployment."""

    deployment_key: str
    required_tpm: int
    optional_tpm: int
    available_tpm: int
    existing_allocated_tpm: int
    reserve_tpm: int
    combined_reserve_tpm: int
    required_capabilities: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        """Return whether available quota covers demand and reserve."""

        free = self.available_tpm - self.existing_allocated_tpm - self.reserve_tpm
        return free >= self.required_tpm

    @property
    def optional_sufficient(self) -> bool:
        """Return whether quota also covers every optional capability."""

        free = self.available_tpm - self.existing_allocated_tpm - self.combined_reserve_tpm
        return free >= self.required_tpm + self.optional_tpm


def plan_capacity(
    demands: tuple[CapabilityDemand, ...],
    *,
    available_tpm_by_deployment: dict[str, int],
    existing_tpm_by_deployment: dict[str, int] | None = None,
) -> tuple[DeploymentCapacity, ...]:
    """Aggregate shared deployment demand and fail closed on missing quota evidence."""

    if not demands:
        raise ValueError("model capacity plan MUST contain capabilities")
    if not any(demand.required for demand in demands):
        raise ValueError("model capacity plan MUST contain a required capability")
    existing = existing_tpm_by_deployment or {}
    grouped: dict[str, list[CapabilityDemand]] = {}
    for demand in demands:
        grouped.setdefault(demand.deployment_key, []).append(demand)
    result: list[DeploymentCapacity] = []
    for key in sorted(grouped):
        if key not in available_tpm_by_deployment:
            raise ValueError(f"quota evidence is missing for deployment {key!r}")
        group = grouped[key]
        required_tpm = sum(item.envelope.minimum_tpm for item in group if item.required)
        optional_tpm = sum(item.envelope.minimum_tpm for item in group if not item.required)
        required_reserve_ratio = max(
            (item.envelope.quota_reserve for item in group if item.required),
            default=0.0,
        )
        combined_reserve_ratio = max(item.envelope.quota_reserve for item in group)
        available = available_tpm_by_deployment[key]
        if available < 0 or existing.get(key, 0) < 0:
            raise ValueError("quota values MUST be non-negative")
        reserve = math.ceil(available * required_reserve_ratio)
        combined_reserve = math.ceil(available * combined_reserve_ratio)
        result.append(
            DeploymentCapacity(
                deployment_key=key,
                required_tpm=required_tpm,
                optional_tpm=optional_tpm,
                available_tpm=available,
                existing_allocated_tpm=existing.get(key, 0),
                reserve_tpm=reserve,
                combined_reserve_tpm=combined_reserve,
                required_capabilities=tuple(
                    sorted(item.capability for item in group if item.required)
                ),
            )
        )
    return tuple(result)
