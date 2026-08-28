"""Package-owned deterministic guard for Cost Governance candidates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class FinOpsEnvironment(StrEnum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class FinOpsActionKind(StrEnum):
    SHUTDOWN = "shutdown"
    RIGHT_SIZE = "right_size"
    SPOT_ADOPT = "spot_adopt"
    AUTOSCALE_ADJUST = "autoscale_adjust"


@dataclass(frozen=True, slots=True)
class ResourceContext:
    resource_id: str
    environment: FinOpsEnvironment
    tags: frozenset[str] = field(default_factory=frozenset)
    current_capacity: int = 0
    dependent_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FinOpsCandidate:
    action_id: str
    kind: FinOpsActionKind
    resource: ResourceContext
    target_capacity: int | None = None


class FinOpsGuardOutcome(StrEnum):
    ALLOWED = "allowed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class FinOpsGuardConfig:
    exclusion_tag: str = "finops:opt-out"
    production_environments: frozenset[FinOpsEnvironment] = frozenset({FinOpsEnvironment.PROD})
    min_capacity_floor: int = 1


@dataclass(frozen=True, slots=True)
class FinOpsGuardDecision:
    action_id: str
    outcome: FinOpsGuardOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


class FinOpsGuard:
    """Evaluate candidates without granting execution or approval authority."""

    def __init__(self, *, config: FinOpsGuardConfig | None = None) -> None:
        self._config = config or FinOpsGuardConfig()
        if self._config.min_capacity_floor < 1:
            raise ValueError("min_capacity_floor MUST be >= 1")

    def evaluate(self, candidate: FinOpsCandidate) -> FinOpsGuardDecision:
        reasons: list[str] = []
        if self._config.exclusion_tag in candidate.resource.tags:
            reasons.append(f"exclusion_tag:{self._config.exclusion_tag}")
        if (
            candidate.kind in (FinOpsActionKind.SHUTDOWN, FinOpsActionKind.RIGHT_SIZE)
            and candidate.resource.environment in self._config.production_environments
        ):
            reasons.append(f"production_environment_locked:{candidate.resource.environment.value}")
        if candidate.kind is FinOpsActionKind.SHUTDOWN and candidate.resource.dependent_ids:
            reasons.append(
                f"shutdown_would_strand_dependents:count={len(candidate.resource.dependent_ids)}"
            )
        if candidate.kind is FinOpsActionKind.RIGHT_SIZE:
            if candidate.target_capacity is None:
                reasons.append("right_size_missing_target_capacity")
            elif candidate.target_capacity < self._config.min_capacity_floor:
                reasons.append(
                    f"target_capacity={candidate.target_capacity}<"
                    f"min_capacity_floor={self._config.min_capacity_floor}"
                )
        outcome = FinOpsGuardOutcome.REJECTED if reasons else FinOpsGuardOutcome.ALLOWED
        return FinOpsGuardDecision(candidate.action_id, outcome, tuple(reasons))

    def evaluate_all(
        self,
        candidates: Iterable[FinOpsCandidate],
    ) -> tuple[FinOpsGuardDecision, ...]:
        return tuple(self.evaluate(candidate) for candidate in candidates)


__all__ = [
    "FinOpsActionKind",
    "FinOpsCandidate",
    "FinOpsEnvironment",
    "FinOpsGuard",
    "FinOpsGuardConfig",
    "FinOpsGuardDecision",
    "FinOpsGuardOutcome",
    "ResourceContext",
]
