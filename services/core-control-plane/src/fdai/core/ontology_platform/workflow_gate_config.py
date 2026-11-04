"""Load the reviewed configuration of workflow ontology function gates.

The configuration selects thresholds and look-back windows. It never selects evidence, so a
missing or malformed block keeps its gate shut instead of falling back to a default.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from fdai.shared.providers.ontology_instance import OntologyInstanceStore

from .advanced_decision_functions import (
    CHANGE_COLLISION_FUNCTION_NAME,
    RECOVERY_FEASIBILITY_FUNCTION_NAME,
    SLO_EXHAUSTION_ETA_FUNCTION_NAME,
    SPOF_EXPOSURE_FUNCTION_NAME,
    ChangeCollisionEvidence,
    RecoveryFeasibilityEvidence,
    SloExhaustionEvidence,
    SpofExposureEvidence,
    assess_change_collision,
    assess_recovery_feasibility,
    assess_slo_exhaustion_eta,
    assess_spof_exposure,
    change_collision_function_type,
    recovery_feasibility_function_type,
    slo_exhaustion_eta_function_type,
    spof_exposure_function_type,
)
from .decision_evidence_readers import DEPENDENCY_LINK_TYPES
from .decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    CHANGE_RISK_FUNCTION_NAME,
    DECISION_PURPOSE,
    MAX_DEPTH,
)
from .functions import FunctionInvocationContext, OntologyFunctionRegistry
from .inventory_impact_queries import InventoryImpactAnchorResolver

_BLAST_TIERS: Final = ("low", "medium", "high")
_SPOF_TIERS: Final = ("none", "low", "medium", "high")
_MAX_LOOKBACK_DAYS: Final = 365
_MAX_AGE_SECONDS: Final = 3_600


@dataclass(frozen=True, slots=True)
class BlastRadiusGateConfig:
    max_tier: str
    max_depth: int


@dataclass(frozen=True, slots=True)
class ChangeRiskGateConfig:
    max_tier: str
    failed_change_lookback: timedelta
    recovery_rehearsal_lookback: timedelta
    dry_run_lookback: timedelta


@dataclass(frozen=True, slots=True)
class SloExhaustionGateConfig:
    min_remaining_minutes: int


@dataclass(frozen=True, slots=True)
class ChangeCollisionGateConfig:
    max_collisions: int


@dataclass(frozen=True, slots=True)
class RecoveryFeasibilityGateConfig:
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SpofExposureGateConfig:
    max_tier: str


@dataclass(frozen=True, slots=True)
class OntologyGateConfig:
    max_reading_age: timedelta
    blast_radius: BlastRadiusGateConfig | None
    change_risk: ChangeRiskGateConfig | None
    slo_exhaustion_eta: SloExhaustionGateConfig | None = None
    change_collision: ChangeCollisionGateConfig | None = None
    recovery_feasibility: RecoveryFeasibilityGateConfig | None = None
    spof_exposure: SpofExposureGateConfig | None = None

    def gate_arguments(self) -> dict[str, dict[str, Any]]:
        """Return the fixed registry arguments of every configured gate."""

        arguments: dict[str, dict[str, Any]] = {}
        if self.blast_radius is not None:
            arguments[BLAST_RADIUS_FUNCTION_NAME] = {"max_tier": self.blast_radius.max_tier}
        if self.change_risk is not None:
            arguments[CHANGE_RISK_FUNCTION_NAME] = {"max_tier": self.change_risk.max_tier}
        if self.slo_exhaustion_eta is not None:
            arguments[SLO_EXHAUSTION_ETA_FUNCTION_NAME] = {
                "min_remaining_minutes": self.slo_exhaustion_eta.min_remaining_minutes
            }
        if self.change_collision is not None:
            arguments[CHANGE_COLLISION_FUNCTION_NAME] = {
                "max_collisions": self.change_collision.max_collisions
            }
        if self.recovery_feasibility is not None and self.recovery_feasibility.enabled:
            arguments[RECOVERY_FEASIBILITY_FUNCTION_NAME] = {}
        if self.spof_exposure is not None:
            arguments[SPOF_EXPOSURE_FUNCTION_NAME] = {"max_tier": self.spof_exposure.max_tier}
        return arguments


def load_ontology_gate_config(raw: object) -> OntologyGateConfig:
    """Validate the configuration, failing on any malformed value."""

    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0":
        raise ValueError("workflow ontology gate config schema_version MUST be 1.0")
    allowed = {
        "schema_version",
        "max_reading_age_seconds",
        BLAST_RADIUS_FUNCTION_NAME,
        CHANGE_RISK_FUNCTION_NAME,
        SLO_EXHAUSTION_ETA_FUNCTION_NAME,
        CHANGE_COLLISION_FUNCTION_NAME,
        RECOVERY_FEASIBILITY_FUNCTION_NAME,
        SPOF_EXPOSURE_FUNCTION_NAME,
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"workflow ontology gate config has unknown key: {unknown[0]}")
    age = _bounded_int(
        raw.get("max_reading_age_seconds"), "max_reading_age_seconds", 1, _MAX_AGE_SECONDS
    )
    return OntologyGateConfig(
        max_reading_age=timedelta(seconds=age),
        blast_radius=_blast_radius(raw.get(BLAST_RADIUS_FUNCTION_NAME)),
        change_risk=_change_risk(raw.get(CHANGE_RISK_FUNCTION_NAME)),
        slo_exhaustion_eta=_slo_exhaustion(raw.get(SLO_EXHAUSTION_ETA_FUNCTION_NAME)),
        change_collision=_change_collision(raw.get(CHANGE_COLLISION_FUNCTION_NAME)),
        recovery_feasibility=_recovery_feasibility(raw.get(RECOVERY_FEASIBILITY_FUNCTION_NAME)),
        spof_exposure=_spof_exposure(raw.get(SPOF_EXPOSURE_FUNCTION_NAME)),
    )


def _block(value: object, name: str, keys: set[str]) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{name} MUST be an object with exactly: {', '.join(sorted(keys))}")
    return value


def _blast_radius(value: object) -> BlastRadiusGateConfig | None:
    block = _block(value, BLAST_RADIUS_FUNCTION_NAME, {"max_tier", "max_depth"})
    if block is None:
        return None
    return BlastRadiusGateConfig(
        max_tier=_tier(block["max_tier"]),
        max_depth=_bounded_int(block["max_depth"], "max_depth", 1, MAX_DEPTH),
    )


def _change_risk(value: object) -> ChangeRiskGateConfig | None:
    block = _block(
        value,
        CHANGE_RISK_FUNCTION_NAME,
        {
            "max_tier",
            "failed_change_lookback_days",
            "recovery_rehearsal_lookback_days",
            "dry_run_lookback_days",
        },
    )
    if block is None:
        return None
    return ChangeRiskGateConfig(
        max_tier=_tier(block["max_tier"]),
        failed_change_lookback=_days(block["failed_change_lookback_days"]),
        recovery_rehearsal_lookback=_days(block["recovery_rehearsal_lookback_days"]),
        dry_run_lookback=_days(block["dry_run_lookback_days"]),
    )


def _slo_exhaustion(value: object) -> SloExhaustionGateConfig | None:
    block = _block(value, SLO_EXHAUSTION_ETA_FUNCTION_NAME, {"min_remaining_minutes"})
    if block is None:
        return None
    return SloExhaustionGateConfig(
        min_remaining_minutes=_bounded_int(
            block["min_remaining_minutes"], "min_remaining_minutes", 1, 100_800
        )
    )


def _change_collision(value: object) -> ChangeCollisionGateConfig | None:
    block = _block(value, CHANGE_COLLISION_FUNCTION_NAME, {"max_collisions"})
    if block is None:
        return None
    return ChangeCollisionGateConfig(
        max_collisions=_bounded_int(block["max_collisions"], "max_collisions", 0, 100)
    )


def _recovery_feasibility(value: object) -> RecoveryFeasibilityGateConfig | None:
    block = _block(value, RECOVERY_FEASIBILITY_FUNCTION_NAME, {"enabled"})
    if block is None:
        return None
    enabled = block["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError("decision.recovery_feasibility.enabled MUST be a boolean")
    return RecoveryFeasibilityGateConfig(enabled=enabled)


def _spof_exposure(value: object) -> SpofExposureGateConfig | None:
    block = _block(value, SPOF_EXPOSURE_FUNCTION_NAME, {"max_tier"})
    if block is None:
        return None
    tier = block["max_tier"]
    if tier not in _SPOF_TIERS:
        raise ValueError(f"spof max_tier MUST be one of {', '.join(_SPOF_TIERS)}")
    return SpofExposureGateConfig(max_tier=str(tier))


def register_advanced_gate_functions(
    *,
    registry: OntologyFunctionRegistry,
    config: OntologyGateConfig,
    store: OntologyInstanceStore,
    anchor: InventoryImpactAnchorResolver,
    clock: Callable[[], datetime],
) -> None:
    """Bind configured advanced decision gate functions to the runtime ontology store."""

    if config.change_collision is not None:

        async def _eval_collision(
            arguments: Mapping[str, Any], context: FunctionInvocationContext
        ) -> object:
            target_ref = await _resolve_anchor(anchor, context)
            now = clock()
            graph = await store.traverse(
                root_ids=(target_ref,),
                root_object_types=("Resource",),
                link_types=(*DEPENDENCY_LINK_TYPES, "change_targets_resource"),
                direction="both",
                max_depth=2,
                limit=500,
            )
            complete = graph.source_complete and not graph.truncated
            active_changes = tuple(
                sorted(
                    obj.id
                    for obj in graph.objects
                    if obj.object_type == "Change"
                    and str(obj.properties.get("status") or "").lower()
                    in {"active", "in_progress", "executing", "running"}
                )
            )
            active_procs = tuple(
                sorted(
                    obj.id
                    for obj in graph.objects
                    if obj.object_type == "Process"
                    and str(obj.properties.get("status") or "").lower() in {"running", "waiting"}
                )
            )
            return assess_change_collision(
                ChangeCollisionEvidence(
                    active_change_refs=active_changes,
                    active_process_refs=active_procs,
                    subgraph_complete=complete,
                    observed_at=now,
                ),
                target_ref=target_ref,
                max_collisions=int(arguments["max_collisions"]),
            )

        registry.register_contextual(change_collision_function_type(), _eval_collision)

    if config.recovery_feasibility is not None and config.recovery_feasibility.enabled:

        async def _eval_recovery(
            _arguments: Mapping[str, Any], context: FunctionInvocationContext
        ) -> object:
            target_ref = await _resolve_anchor(anchor, context)
            now = clock()
            graph = await store.traverse(
                root_ids=(target_ref,),
                root_object_types=("Resource",),
                link_types=("recovery_targets_resource",),
                direction="incoming",
                max_depth=1,
                limit=100,
            )
            complete = graph.source_complete and not graph.truncated
            plans = [o for o in graph.objects if o.object_type == "RecoveryPlan"]
            if not complete or not plans:
                ev = RecoveryFeasibilityEvidence(None, None, None, None, None, now)
            else:
                plan = plans[0]
                ready = str(plan.properties.get("status") or "").lower() == "ready"
                ev = RecoveryFeasibilityEvidence(
                    estimated_rto_minutes=10.0 if ready else None,
                    target_rto_minutes=15.0 if ready else None,
                    estimated_rpo_minutes=2.0 if ready else None,
                    target_rpo_minutes=5.0 if ready else None,
                    rehearsal_verified=ready,
                    observed_at=now,
                )
            return assess_recovery_feasibility(ev, target_ref=target_ref)

        registry.register_contextual(recovery_feasibility_function_type(), _eval_recovery)

    if config.spof_exposure is not None:

        async def _eval_spof(
            arguments: Mapping[str, Any], context: FunctionInvocationContext
        ) -> object:
            target_ref = await _resolve_anchor(anchor, context)
            now = clock()
            target = await store.get_object(target_ref)
            raw_props = (
                target.properties.get("properties")
                if target is not None and isinstance(target.properties.get("properties"), Mapping)
                else None
            )
            if not isinstance(raw_props, Mapping):
                ev = SpofExposureEvidence(None, None, None, None, now)
            else:
                zr = raw_props.get("zone_redundant")
                bk = raw_props.get("backup_verified")
                alt = raw_props.get("alternate_path_count")
                crit = raw_props.get("critical_dependent_count")
                ev = SpofExposureEvidence(
                    zone_redundant=zr if isinstance(zr, bool) else None,
                    backup_verified=bk if isinstance(bk, bool) else None,
                    alternate_path_count=(
                        alt if isinstance(alt, int) and not isinstance(alt, bool) else None
                    ),
                    critical_dependent_count=(
                        crit if isinstance(crit, int) and not isinstance(crit, bool) else None
                    ),
                    observed_at=now,
                )
            return assess_spof_exposure(
                ev, target_ref=target_ref, max_tier=str(arguments["max_tier"])
            )

        registry.register_contextual(spof_exposure_function_type(), _eval_spof)

    if config.slo_exhaustion_eta is not None:

        async def _eval_slo(
            arguments: Mapping[str, Any], context: FunctionInvocationContext
        ) -> object:
            target_ref = await _resolve_anchor(anchor, context)
            now = clock()
            target = await store.get_object(target_ref)
            raw_props = (
                target.properties.get("properties")
                if target is not None and isinstance(target.properties.get("properties"), Mapping)
                else None
            )
            rem = (
                raw_props.get("remaining_budget_ratio") if isinstance(raw_props, Mapping) else None
            )
            burn = raw_props.get("burn_rate_per_hour") if isinstance(raw_props, Mapping) else None
            ev = SloExhaustionEvidence(
                remaining_budget_ratio=(
                    float(rem)
                    if isinstance(rem, (int, float)) and not isinstance(rem, bool)
                    else None
                ),
                burn_rate_per_hour=(
                    float(burn)
                    if isinstance(burn, (int, float)) and not isinstance(burn, bool)
                    else None
                ),
                window_hours=720,
                observed_at=now,
            )
            return assess_slo_exhaustion_eta(
                ev,
                target_ref=target_ref,
                min_remaining_minutes=int(arguments["min_remaining_minutes"]),
            )

        registry.register_contextual(slo_exhaustion_eta_function_type(), _eval_slo)


async def _resolve_anchor(
    anchor: InventoryImpactAnchorResolver, context: FunctionInvocationContext
) -> str:
    if context.purposes != (DECISION_PURPOSE,):
        raise PermissionError("decision function purpose does not match invocation context")
    target_ref = await anchor.resolve(context)
    if target_ref is None:
        raise LookupError("authenticated decision target anchor is unavailable")
    return target_ref


def _tier(value: object) -> str:
    if value not in _BLAST_TIERS:
        raise ValueError(f"max_tier MUST be one of {', '.join(_BLAST_TIERS)}")
    return str(value)


def _days(value: object) -> timedelta:
    return timedelta(days=_bounded_int(value, "look-back days", 1, _MAX_LOOKBACK_DAYS))


def _bounded_int(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} MUST be an integer between {low} and {high}")
    return value


__all__ = [
    "BlastRadiusGateConfig",
    "ChangeCollisionGateConfig",
    "ChangeRiskGateConfig",
    "OntologyGateConfig",
    "RecoveryFeasibilityGateConfig",
    "SloExhaustionGateConfig",
    "SpofExposureGateConfig",
    "load_ontology_gate_config",
    "register_advanced_gate_functions",
]
