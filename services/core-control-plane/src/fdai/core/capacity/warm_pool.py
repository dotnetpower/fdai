"""Warm-capacity policy - resolve the cold-start vs MTTR tension (#30).

Scale-to-zero is the right default: an idle control plane should cost
nothing. But a cold start adds seconds-to-tens-of-seconds of wake latency,
and that latency lands directly on **MTTR** for an urgent recovery - a
SEV1 failover cannot wait for a container to boot. This policy decides,
deterministically, which work warrants **warm** (pre-provisioned,
min-replicas > 0) execution capacity and which can tolerate scale-to-zero.

The policy is a **pure function of explicit inputs** - severity, storm
state, and off-hours - and holds no I/O. The deployment layer
(`infra/`, Container Apps min-replica config) reads the recommended
`min_replicas` at plan time; the runtime reads `warm_required` to decide
whether to keep a warm lane for a given action class. It never widens
capacity on its own; it emits a recommendation the caller applies.

Rationale for each warm trigger:

- **High severity** (SEV1/SEV2): the cold-start delay is a direct MTTR
  cost the incident cannot absorb.
- **Storm active**: during an event storm a burst of remediations arrives
  together; cold-starting each one serializes recovery
  ([StormCoordinator](../incident/storm.py)).
- **Off-hours**: with no human already warm at the console, autonomous
  recovery is the only fast path, so the executor lane must be warm.

Design contract: [cost-model.md](../../../../docs/roadmap/interfaces/cost-model.md)
(cost envelope) and
[app-shape.instructions.md](../../../../.github/instructions/app-shape.instructions.md)
(scale-to-zero runtime).
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.contracts.models import IncidentSeverity

# Severity rank: SEV1 (most severe) -> 1 ... SEV5 -> 5. A lower rank is a
# more urgent incident, so "at or above the threshold severity" means a
# rank <= the configured threshold rank.
_SEVERITY_RANK: dict[IncidentSeverity, int] = {
    IncidentSeverity.SEV1: 1,
    IncidentSeverity.SEV2: 2,
    IncidentSeverity.SEV3: 3,
    IncidentSeverity.SEV4: 4,
    IncidentSeverity.SEV5: 5,
}


@dataclass(frozen=True, slots=True)
class WarmCapacityConfig:
    """Fork-tunable thresholds for the warm-capacity decision.

    All fields are configuration, not literals in the policy, so a fork
    tunes the cost / latency trade-off without editing this module.
    """

    warm_at_or_above_severity: IncidentSeverity = IncidentSeverity.SEV2
    """Incidents at this severity or more severe warrant warm capacity."""

    storm_forces_warm: bool = True
    """An active event storm forces warm capacity regardless of severity."""

    off_hours_forces_warm: bool = True
    """Off-hours (no human warm at the console) forces warm capacity."""

    cold_min_replicas: int = 0
    """Replica floor when warm is not required (scale-to-zero)."""

    warm_min_replicas: int = 1
    """Replica floor when warm is required."""

    def __post_init__(self) -> None:
        if self.cold_min_replicas < 0:
            raise ValueError("cold_min_replicas MUST be >= 0")
        if self.warm_min_replicas < 1:
            raise ValueError("warm_min_replicas MUST be >= 1 (warm means not zero)")


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    """The warm-capacity recommendation for one action class + context."""

    warm_required: bool
    min_replicas: int
    triggers: tuple[str, ...]
    """The reasons warm was required (empty when scale-to-zero is fine)."""
    reason: str


class WarmCapacityPolicy:
    """Deterministic warm-vs-cold executor-capacity policy."""

    def __init__(self, config: WarmCapacityConfig | None = None) -> None:
        self._config = config or WarmCapacityConfig()

    def decide(
        self,
        *,
        severity: IncidentSeverity,
        storm_active: bool = False,
        off_hours: bool = False,
    ) -> CapacityDecision:
        """Return the warm-capacity recommendation for the given context.

        Warm is required when **any** trigger fires: the incident is at or
        above the configured severity, a storm is active (and configured
        to force warm), or it is off-hours (and configured to force warm).
        Otherwise scale-to-zero is recommended. Deterministic: the same
        context always yields the same decision.
        """
        cfg = self._config
        triggers: list[str] = []

        threshold_rank = _SEVERITY_RANK[cfg.warm_at_or_above_severity]
        # Fail-warm on an unknown severity (enum drift): an unmapped severity
        # is treated as the most urgent (rank 1) so a new severity never
        # silently loses warm capacity. Mirrors StormCoordinator's ``.get``.
        if _SEVERITY_RANK.get(severity, 1) <= threshold_rank:
            triggers.append(
                f"severity {severity.value} at/above {cfg.warm_at_or_above_severity.value}"
            )
        if storm_active and cfg.storm_forces_warm:
            triggers.append("storm active")
        if off_hours and cfg.off_hours_forces_warm:
            triggers.append("off-hours (no human warm)")

        warm_required = bool(triggers)
        min_replicas = cfg.warm_min_replicas if warm_required else cfg.cold_min_replicas
        if warm_required:
            reason = f"warm required (min_replicas={min_replicas}): " + "; ".join(triggers)
        else:
            reason = (
                f"scale-to-zero acceptable (min_replicas={min_replicas}): "
                "no warm trigger for this context"
            )
        return CapacityDecision(
            warm_required=warm_required,
            min_replicas=min_replicas,
            triggers=tuple(triggers),
            reason=reason,
        )


__all__ = [
    "CapacityDecision",
    "WarmCapacityConfig",
    "WarmCapacityPolicy",
]
