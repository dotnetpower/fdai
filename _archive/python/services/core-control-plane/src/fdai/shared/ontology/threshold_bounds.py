"""Ontology-declared hard bounds for governed adaptive thresholds.

FDAI-CONST-004 separates meaning from control: the versioned ontology owns the hard
bound, versioned policy owns the active value inside it, and a learned candidate is inert
until promotion. A runtime threshold that restates its bound as a literal breaks that
separation quietly - the literal can be widened past the declaration and nothing fails.

This module is the read side of that rule. It loads the numeric bounds declared by the
shipped ``ontology/action-type`` and ``ontology/detection-routing-bounds`` contracts and
offers one checker, so runtime thresholds can bind to versioned semantic limits instead
of relying on an unregistered copy.

Nothing here promotes, judges, or executes. A bound only ever narrows what a threshold may
be; it never grants permission to use one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType

from fdai.shared.contracts.registry import PackageResourceSchemaRegistry, SchemaRegistry

#: Schema name and version this module reads. Pinned rather than "latest" so a new
#: contract version is an explicit change here.
ACTION_TYPE_SCHEMA = ("ontology/action-type", "1.0.0")

#: Schema name and version for production routing and detection hard bounds.
#: The package registry remains a static source table; resolving this pin never depends on
#: an ontology read, which avoids a circular registry bootstrap.
DETECTION_ROUTING_SCHEMA = ("ontology/detection-routing-bounds", "1.0.0")

#: Semantic id prefix for every bound this module owns today.
PROMOTION_GATE_PREFIX = "promotion_gate"

#: Semantic groups declared by :data:`DETECTION_ROUTING_SCHEMA`.
DETECTION_ROUTING_GROUPS = ("llm_routing", "incident_detection")


class BoundValueType(StrEnum):
    """JSON Schema numeric type a bounded value must match."""

    INTEGER = "integer"
    NUMBER = "number"


@dataclass(frozen=True, slots=True)
class HardBound:
    """One ontology-declared inclusive numeric bound."""

    semantic_id: str
    value_type: BoundValueType
    minimum: Decimal | None
    maximum: Decimal | None
    unit: str
    scope: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.semantic_id.strip():
            raise ValueError("HardBound.semantic_id MUST be non-empty")
        if not self.unit.strip():
            raise ValueError(f"HardBound {self.semantic_id!r} MUST declare a unit")
        if not self.scope.strip():
            raise ValueError(f"HardBound {self.semantic_id!r} MUST declare a scope")
        if self.minimum is None and self.maximum is None:
            raise ValueError(f"HardBound {self.semantic_id!r} MUST declare a minimum or a maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"HardBound {self.semantic_id!r} minimum exceeds its maximum")


@dataclass(frozen=True, slots=True)
class BoundViolation:
    """Why one candidate value is outside its declared hard bound."""

    semantic_id: str
    reason_code: str
    value: object


class UnknownBoundError(KeyError):
    """Raised when a semantic id has no declared bound."""


def load_promotion_gate_bounds(registry: SchemaRegistry | None = None) -> Mapping[str, HardBound]:
    """Return the promotion-gate bounds declared by the shipped ActionType contract."""

    source = registry or PackageResourceSchemaRegistry()
    schema = source.get(*ACTION_TYPE_SCHEMA)
    gate = _object(_object(schema, "properties"), PROMOTION_GATE_PREFIX)
    declared = _object(gate, "properties")

    bounds = _load_declared_bounds(
        declared,
        semantic_prefix=PROMOTION_GATE_PREFIX,
        schema_ref=ACTION_TYPE_SCHEMA,
        pointer_prefix=f"/properties/{PROMOTION_GATE_PREFIX}/properties",
    )
    if not bounds:
        raise ValueError("the shipped ActionType contract declares no promotion-gate bound")
    return MappingProxyType(dict(sorted(bounds.items())))


def load_detection_routing_bounds(
    registry: SchemaRegistry | None = None,
) -> Mapping[str, HardBound]:
    """Return hard bounds for production LLM routing and incident detection controls."""

    source = registry or PackageResourceSchemaRegistry()
    schema = source.get(*DETECTION_ROUTING_SCHEMA)
    root_properties = _object(schema, "properties")
    bounds: dict[str, HardBound] = {}
    for group_name in DETECTION_ROUTING_GROUPS:
        group = _object(root_properties, group_name)
        declared = _object(group, "properties")
        group_bounds = _load_declared_bounds(
            declared,
            semantic_prefix=group_name,
            schema_ref=DETECTION_ROUTING_SCHEMA,
            pointer_prefix=f"/properties/{group_name}/properties",
        )
        overlap = set(bounds) & set(group_bounds)
        if overlap:  # pragma: no cover - distinct semantic prefixes make this defensive
            raise ValueError(f"duplicate detection-routing semantic ids: {sorted(overlap)!r}")
        bounds.update(group_bounds)
    if not bounds:
        raise ValueError("the detection-routing contract declares no numeric hard bound")
    return MappingProxyType(dict(sorted(bounds.items())))


def check_within_bounds(
    semantic_id: str,
    value: object,
    bounds: Mapping[str, HardBound],
) -> BoundViolation | None:
    """Return why ``value`` is outside its declared bound, or ``None`` when it is inside."""

    bound = bounds.get(semantic_id)
    if bound is None:
        raise UnknownBoundError(semantic_id)

    if isinstance(value, bool):
        return BoundViolation(semantic_id, "value_type_invalid", value)
    if bound.value_type is BoundValueType.INTEGER:
        if not isinstance(value, int):
            return BoundViolation(semantic_id, "value_type_invalid", value)
    elif not isinstance(value, (int, float)):
        return BoundViolation(semantic_id, "value_type_invalid", value)
    if isinstance(value, float) and not math.isfinite(value):
        return BoundViolation(semantic_id, "value_not_finite", value)

    try:
        candidate = Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - guarded by the type checks above
        return BoundViolation(semantic_id, "value_type_invalid", value)

    if bound.minimum is not None and candidate < bound.minimum:
        return BoundViolation(semantic_id, "below_minimum", value)
    if bound.maximum is not None and candidate > bound.maximum:
        return BoundViolation(semantic_id, "above_maximum", value)
    return None


#: Every numeric runtime threshold that an ontology bound governs today, mapped to the
#: semantic id that bounds it. A runtime threshold missing from both this table and
#: :data:`UNBOUND_ADAPTIVE_THRESHOLDS` is an unrecorded gap, which the focused test fails on.
ADAPTIVE_THRESHOLD_BINDINGS: Mapping[str, str] = MappingProxyType(
    {
        "GraphModelPromotionPolicy.max_policy_escapes": "promotion_gate.max_policy_escapes",
        "GraphModelPromotionPolicy.max_recurrence_rate": "promotion_gate.max_recurrence_rate",
        "GraphModelPromotionPolicy.min_fidelity": "promotion_gate.min_fidelity",
        "GraphModelPromotionPolicy.min_samples": "promotion_gate.min_samples",
        "ShadowDwellThresholds.min_accuracy": "promotion_gate.min_accuracy",
        "ShadowDwellThresholds.min_samples": "promotion_gate.min_samples",
        "ShadowDwellThresholds.min_shadow_days": "promotion_gate.min_shadow_days",
        "shadow_dwell.MAX_POLICY_ESCAPES": "promotion_gate.max_policy_escapes",
    }
)

#: Every production routing and detection threshold discovered at its active consumer,
#: mapped to the semantic hard bound that limits its versioned configuration value.
#: The focused AST test enforces an exact, non-vacuous bijection between consumers and this
#: registry, then proves the active config declarations match the ontology bounds.
DETECTION_ROUTING_THRESHOLD_BINDINGS: Mapping[str, str] = MappingProxyType(
    {
        "incident.alert_rate_per_hour": "incident_detection.alert_rate_per_hour",
        "incident.repeat_threshold": "incident_detection.repeat_threshold",
        "incident.repeat_window_seconds": "incident_detection.repeat_window_seconds",
        "incident.security_high_threshold": "incident_detection.security_high_threshold",
        "incident.security_window_events": "incident_detection.security_window_events",
        "quality_gate_confidence_threshold": "llm_routing.quality_gate_confidence_threshold",
        "quality_gate_quorum": "llm_routing.quality_gate_quorum",
        "self_consistency_sample_threshold": "llm_routing.self_consistency_sample_threshold",
        "self_consistency_samples": "llm_routing.self_consistency_samples",
        "self_consistency_stability_threshold": "llm_routing.self_consistency_stability_threshold",
        "t1_min_success_rate": "llm_routing.t1_min_success_rate",
        "t1_similarity_threshold": "llm_routing.t1_similarity_threshold",
    }
)

#: Numeric runtime thresholds the shipped ontology does not declare a bound for yet. The set is
#: empty today; it stays because the focused test needs somewhere to record a future gap
#: explicitly rather than letting an undeclared threshold pass unnoticed.
UNBOUND_ADAPTIVE_THRESHOLDS: frozenset[str] = frozenset()


def _object(node: Mapping[str, object], key: str) -> Mapping[str, object]:
    child = node.get(key)
    if not isinstance(child, Mapping):
        raise ValueError(f"the threshold-bound contract is missing the {key!r} object")
    return child


def _load_declared_bounds(
    declared: Mapping[str, object],
    *,
    semantic_prefix: str,
    schema_ref: tuple[str, str],
    pointer_prefix: str,
) -> dict[str, HardBound]:
    """Extract inclusive numeric bounds and required semantic annotations."""

    bounds: dict[str, HardBound] = {}
    for field_name, raw in declared.items():
        if not isinstance(raw, Mapping):
            continue
        semantic_id = f"{semantic_prefix}.{field_name}"
        if "exclusiveMinimum" in raw or "exclusiveMaximum" in raw:
            raise ValueError(
                f"{semantic_id} declares an exclusive bound, which this loader does not model"
            )
        minimum = _decimal(raw.get("minimum"))
        maximum = _decimal(raw.get("maximum"))
        if minimum is None and maximum is None:
            continue
        declared_type = raw.get("type")
        if declared_type not in tuple(BoundValueType):
            continue
        unit = raw.get("x-fdai-unit")
        scope = raw.get("x-fdai-scope")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"{semantic_id} MUST declare x-fdai-unit")
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError(f"{semantic_id} MUST declare x-fdai-scope")
        bounds[semantic_id] = HardBound(
            semantic_id=semantic_id,
            value_type=BoundValueType(declared_type),
            minimum=minimum,
            maximum=maximum,
            unit=unit,
            scope=scope,
            source_ref=f"{schema_ref[0]}@{schema_ref[1]}#{pointer_prefix}/{field_name}",
        )
    return bounds


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


__all__ = [
    "ACTION_TYPE_SCHEMA",
    "ADAPTIVE_THRESHOLD_BINDINGS",
    "DETECTION_ROUTING_GROUPS",
    "DETECTION_ROUTING_SCHEMA",
    "DETECTION_ROUTING_THRESHOLD_BINDINGS",
    "PROMOTION_GATE_PREFIX",
    "UNBOUND_ADAPTIVE_THRESHOLDS",
    "BoundValueType",
    "BoundViolation",
    "HardBound",
    "UnknownBoundError",
    "check_within_bounds",
    "load_detection_routing_bounds",
    "load_promotion_gate_bounds",
]
