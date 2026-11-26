"""FinOps vertical guardrails.

Phase 3 § FinOps. The FinOps vertical produces candidate cost actions
(idle shutdown, right-sizing, spot/autoscale) that the shared
`trust-router` and `risk-gate` govern like any other action. On top of
the risk-gate's generic invariants, FinOps carries its own guardrails
per phase-3 doc:

- respect **exclusion / opt-out tags** on the target resource;
- **protect production**: no auto scale-down or shutdown on production
  resources;
- honor **minimum-capacity floors** so a shutdown cannot strand a
  dependent workload;
- honor **dependency checks**: a resource with unresolved dependents
  cannot be shut down;
- **idempotent** and **reversible** - enforced by the executor / PR
  publisher layer, so this module only rejects candidates that cannot
  meet the other guardrails.

Every guard is a *rejection reason*; the caller (a P3 orchestrator)
turns rejections into HIL escalations + audit entries.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class FinOpsEnvironment(StrEnum):
    """Resource environment tag."""

    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class FinOpsActionKind(StrEnum):
    """Cost-vertical action categories."""

    SHUTDOWN = "shutdown"
    RIGHT_SIZE = "right_size"
    SPOT_ADOPT = "spot_adopt"
    AUTOSCALE_ADJUST = "autoscale_adjust"


@dataclass(frozen=True, slots=True)
class ResourceContext:
    """Everything the FinOps guardrail needs about the target resource.

    Deliberately small - the inventory adapter fills this; ``core/``
    never queries Azure directly (see G2 core-imports guard).
    """

    resource_id: str
    environment: FinOpsEnvironment
    tags: frozenset[str] = field(default_factory=frozenset)
    current_capacity: int = 0
    """Current instance / replica count. 0 → not a scalable resource."""

    dependent_ids: tuple[str, ...] = field(default_factory=tuple)
    """Resources that depend on this one; a shutdown MUST resolve them
    (through their own separate audit entries) before firing."""


@dataclass(frozen=True, slots=True)
class FinOpsCandidate:
    """A cost action candidate handed to the guardrails."""

    action_id: str
    kind: FinOpsActionKind
    resource: ResourceContext
    target_capacity: int | None = None
    """Proposed new replica count on RIGHT_SIZE - non-null and
    ``>= min_capacity_floor`` for the guardrail to pass. AUTOSCALE_ADJUST is
    a policy change (adjusting the autoscale bounds), governed generically by
    the risk-gate rather than by the FinOps capacity floor, so it intentionally
    does NOT require this field or trip the production scale-down lock (see
    ``test_autoscale_adjust_allowed_in_prod_without_scale_down_guard``)."""


class FinOpsGuardOutcome(StrEnum):
    """Terminal outcome for one guardrail evaluation."""

    ALLOWED = "allowed"
    """All guards passed. Candidate proceeds to the risk-gate."""

    REJECTED = "rejected"
    """A guard blocked the candidate. Reasons list carries the whys."""


@dataclass(frozen=True, slots=True)
class FinOpsGuardConfig:
    """Guardrail policy knobs - every value is auditable config."""

    exclusion_tag: str = "finops:opt-out"
    """Resources tagged with this MUST NOT be auto-modified."""

    production_environments: frozenset[FinOpsEnvironment] = frozenset({FinOpsEnvironment.PROD})
    """Environments where scale-down / shutdown auto is forbidden."""

    min_capacity_floor: int = 1
    """Right-size candidates must not push below this replica count."""


@dataclass(frozen=True, slots=True)
class FinOpsGuardDecision:
    """Frozen record per candidate."""

    action_id: str
    outcome: FinOpsGuardOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


class FinOpsGuard:
    """Compose the four FinOps guardrail checks."""

    def __init__(self, *, config: FinOpsGuardConfig | None = None) -> None:
        cfg = config or FinOpsGuardConfig()
        if cfg.min_capacity_floor < 1:
            raise ValueError("min_capacity_floor MUST be >= 1")
        self._config = cfg

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
        return FinOpsGuardDecision(
            action_id=candidate.action_id,
            outcome=outcome,
            reasons=tuple(reasons),
        )

    def evaluate_all(
        self, candidates: Iterable[FinOpsCandidate]
    ) -> tuple[FinOpsGuardDecision, ...]:
        return tuple(self.evaluate(c) for c in candidates)


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
