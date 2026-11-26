"""Deterministic, read-only decision FunctionTypes over receipted evidence.

Three functions turn already-observed ontology evidence into a bounded decision input:
``decision.blast_radius`` weighs the reachable resources by reviewed service criticality,
``decision.change_risk`` combines blast radius with change-safety factors, and
``decision.cost_of_delay`` prices a delay from an observed hourly cost. Each result carries
``complete`` and ``observed_at``. The blast-radius and change-risk results also carry a
``gate_satisfied`` predicate that a workflow ``ontology-function:`` gate can read. A missing or
unreviewed input yields ``unknown`` and a closed predicate, never an optimistic default. The
cost result is a ranking signal and carries no predicate, because a cost threshold is a
business decision that no workflow gate encodes. It never opens a gate: a gate reading without
a boolean predicate is treated as no reading. A reading is advice that can only preserve or
lower autonomy. It grants no execution or mutation authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Protocol

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .inventory_impact_queries import InventoryImpactAnchorResolver

BLAST_RADIUS_FUNCTION_NAME: Final = "decision.blast_radius"
CHANGE_RISK_FUNCTION_NAME: Final = "decision.change_risk"
COST_OF_DELAY_FUNCTION_NAME: Final = "decision.cost_of_delay"
DECISION_PURPOSE: Final = "operations-review"
MAX_IMPACTED_RESOURCES: Final = 1_001
MAX_DEPTH: Final = 5

_TIERS: Final = ("low", "medium", "high", "critical")
_TIER_RANK: Final = {name: index for index, name in enumerate(_TIERS)}
_CRITICALITY_WEIGHT: Final = {"low": 1, "medium": 2, "high": 4, "critical": 8}
# Resource score = criticality weight * (MAX_DEPTH + 1 - depth): nearer dependents weigh more.
_BLAST_TIER_UPPER_BOUNDS: Final = (12, 48, 120)
_BLAST_RISK_POINTS: Final = {"low": 0, "medium": 2, "high": 4, "critical": 6}
_RISK_TIER_UPPER_BOUNDS: Final = (2, 5, 9)
_MAX_FAILED_CHANGE_POINTS: Final = 3
_MAX_DELAY_HOURS: Final = 720
_MAX_DECIMAL_DIGITS: Final = 24
_DIGEST_PATTERN: Final = "^sha256:[a-f0-9]{64}$"


@dataclass(frozen=True, slots=True)
class ImpactedResource:
    """One reached resource with its reviewed business criticality, when known."""

    resource_ref: str
    depth: int
    criticality: str | None


@dataclass(frozen=True, slots=True)
class BlastRadiusEvidence:
    """Receipted reachability evidence for one target."""

    resources: tuple[ImpactedResource, ...]
    traversal_complete: bool
    source_generation: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeRiskEvidence:
    """Receipted change-safety factors; ``None`` means the factor is unobserved."""

    blast_radius_tier: str | None
    change_window_active: bool | None
    recent_failed_changes: int | None
    rollback_tested: bool | None
    dry_run_passed: bool | None
    source_generation: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CostOfDelayEvidence:
    """Receipted hourly cost basis for one target."""

    hourly_cost_amount: Decimal | None
    currency: str | None
    basis_ref: str
    observed_at: datetime


class BlastRadiusEvidenceReader(Protocol):
    async def read(self, *, target_ref: str) -> BlastRadiusEvidence | None: ...


class ChangeRiskEvidenceReader(Protocol):
    async def read(self, *, target_ref: str) -> ChangeRiskEvidence | None: ...


class CostOfDelayEvidenceReader(Protocol):
    async def read(self, *, target_ref: str) -> CostOfDelayEvidence | None: ...


def assess_blast_radius(
    evidence: BlastRadiusEvidence,
    *,
    target_ref: str,
    max_tier: str,
) -> dict[str, object]:
    """Weigh reachable resources by criticality and depth; unknown inputs close the gate."""

    reasons: list[str] = []
    if not evidence.traversal_complete:
        reasons.append("traversal_incomplete")
    if len(evidence.resources) > MAX_IMPACTED_RESOURCES:
        raise ValueError("blast radius evidence exceeds the resource bound")
    refs = [item.resource_ref for item in evidence.resources]
    if len(refs) != len(set(refs)):
        raise ValueError("blast radius evidence MUST list each resource once")
    score = 0
    unreviewed = 0
    for item in evidence.resources:
        if not 0 <= item.depth <= MAX_DEPTH:
            raise ValueError("blast radius depth is outside the traversal bound")
        weight = _CRITICALITY_WEIGHT.get((item.criticality or "").strip().lower())
        if weight is None:
            unreviewed += 1
            continue
        score += weight * (MAX_DEPTH + 1 - item.depth)
    if unreviewed:
        reasons.append("criticality_unreviewed")
    complete = not reasons
    tier = _tier(score, _BLAST_TIER_UPPER_BOUNDS) if complete else "unknown"
    return _result(
        function=BLAST_RADIUS_FUNCTION_NAME,
        target_ref=target_ref,
        tier=tier,
        complete=complete,
        gate_satisfied=complete and _TIER_RANK[tier] <= _TIER_RANK[max_tier],
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={
            "score": score,
            "affected_count": max(len(evidence.resources) - 1, 0),
            "unreviewed_criticality_count": unreviewed,
            "source_generation": evidence.source_generation,
        },
    )


def assess_change_risk(
    evidence: ChangeRiskEvidence,
    *,
    target_ref: str,
    max_tier: str,
) -> dict[str, object]:
    """Score change risk from observed factors; any unobserved factor closes the gate."""

    reasons: list[str] = []
    points = 0
    if evidence.blast_radius_tier in _BLAST_RISK_POINTS:
        points += _BLAST_RISK_POINTS[str(evidence.blast_radius_tier)]
    else:
        reasons.append("blast_radius_unobserved")
    if evidence.change_window_active is None:
        reasons.append("change_window_unobserved")
    elif not evidence.change_window_active:
        points += 3
    failed = evidence.recent_failed_changes
    if failed is None or failed < 0:
        reasons.append("recent_failed_changes_unobserved")
    else:
        points += min(failed, _MAX_FAILED_CHANGE_POINTS)
    if evidence.rollback_tested is None:
        reasons.append("rollback_tested_unobserved")
    elif not evidence.rollback_tested:
        points += 3
    if evidence.dry_run_passed is None:
        reasons.append("dry_run_unobserved")
    elif not evidence.dry_run_passed:
        points += 2
    complete = not reasons
    tier = _tier(points, _RISK_TIER_UPPER_BOUNDS) if complete else "unknown"
    return _result(
        function=CHANGE_RISK_FUNCTION_NAME,
        target_ref=target_ref,
        tier=tier,
        complete=complete,
        gate_satisfied=complete and _TIER_RANK[tier] <= _TIER_RANK[max_tier],
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={"points": points, "source_generation": evidence.source_generation},
    )


def assess_cost_of_delay(
    evidence: CostOfDelayEvidence,
    *,
    target_ref: str,
    delay_hours: int,
) -> dict[str, object]:
    """Price a delay as a ranking signal. It states no threshold and opens no gate."""

    if not 1 <= delay_hours <= _MAX_DELAY_HOURS:
        raise ValueError("delay_hours is outside the reviewed bound")
    reasons: list[str] = []
    rate = evidence.hourly_cost_amount
    if rate is None or not rate.is_finite() or rate < 0:
        reasons.append("hourly_cost_unobserved")
    if not evidence.currency:
        reasons.append("currency_unobserved")
    complete = not reasons
    total = rate * delay_hours if complete and rate is not None else None
    return _result(
        function=COST_OF_DELAY_FUNCTION_NAME,
        target_ref=target_ref,
        tier="unknown" if total is None else "known",
        complete=complete,
        gate_satisfied=None,
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={
            "delay_hours": delay_hours,
            "currency": evidence.currency if complete else None,
            "total_amount": None if total is None else _decimal_text(total),
            "basis_ref": evidence.basis_ref,
        },
    )


def blast_radius_function_type() -> OntologyFunctionType:
    return _declaration(
        BLAST_RADIUS_FUNCTION_NAME,
        {"max_tier": _tier_schema(("low", "medium", "high"))},
        ["max_tier"],
        _output_schema(
            tier_values=(*_TIERS, "unknown"),
            extra={
                "score": {"type": "integer", "minimum": 0},
                "affected_count": {"type": "integer", "minimum": 0},
                "unreviewed_criticality_count": {"type": "integer", "minimum": 0},
                "source_generation": {"type": "string"},
            },
        ),
    )


def change_risk_function_type() -> OntologyFunctionType:
    return _declaration(
        CHANGE_RISK_FUNCTION_NAME,
        {"max_tier": _tier_schema(("low", "medium", "high"))},
        ["max_tier"],
        _output_schema(
            tier_values=(*_TIERS, "unknown"),
            extra={
                "points": {"type": "integer", "minimum": 0},
                "source_generation": {"type": "string"},
            },
        ),
    )


def cost_of_delay_function_type() -> OntologyFunctionType:
    return _declaration(
        COST_OF_DELAY_FUNCTION_NAME,
        {"delay_hours": {"type": "integer", "minimum": 1, "maximum": _MAX_DELAY_HOURS}},
        ["delay_hours"],
        _output_schema(
            tier_values=("known", "unknown"),
            gated=False,
            extra={
                "delay_hours": {"type": "integer"},
                "currency": {"type": ["string", "null"]},
                "total_amount": {"type": ["string", "null"]},
                "basis_ref": {"type": "string"},
            },
        ),
    )


def blast_radius_function(
    *,
    reader: BlastRadiusEvidenceReader,
    anchor_resolver: InventoryImpactAnchorResolver,
) -> ContextualOntologyFunction:
    async def evaluate(arguments: Mapping[str, Any], context: FunctionInvocationContext) -> object:
        target_ref = await _anchor(anchor_resolver, context)
        evidence = await reader.read(target_ref=target_ref)
        if evidence is None:
            raise LookupError("blast radius evidence is unavailable")
        _require_aware(evidence.observed_at)
        return assess_blast_radius(
            evidence, target_ref=target_ref, max_tier=str(arguments["max_tier"])
        )

    return evaluate


def change_risk_function(
    *,
    reader: ChangeRiskEvidenceReader,
    anchor_resolver: InventoryImpactAnchorResolver,
) -> ContextualOntologyFunction:
    async def evaluate(arguments: Mapping[str, Any], context: FunctionInvocationContext) -> object:
        target_ref = await _anchor(anchor_resolver, context)
        evidence = await reader.read(target_ref=target_ref)
        if evidence is None:
            raise LookupError("change risk evidence is unavailable")
        _require_aware(evidence.observed_at)
        return assess_change_risk(
            evidence, target_ref=target_ref, max_tier=str(arguments["max_tier"])
        )

    return evaluate


def cost_of_delay_function(
    *,
    reader: CostOfDelayEvidenceReader,
    anchor_resolver: InventoryImpactAnchorResolver,
) -> ContextualOntologyFunction:
    async def evaluate(arguments: Mapping[str, Any], context: FunctionInvocationContext) -> object:
        target_ref = await _anchor(anchor_resolver, context)
        evidence = await reader.read(target_ref=target_ref)
        if evidence is None:
            raise LookupError("cost of delay evidence is unavailable")
        _require_aware(evidence.observed_at)
        return assess_cost_of_delay(
            evidence,
            target_ref=target_ref,
            delay_hours=int(arguments["delay_hours"]),
        )

    return evaluate


def decision_function_types() -> tuple[OntologyFunctionType, ...]:
    return (
        blast_radius_function_type(),
        change_risk_function_type(),
        cost_of_delay_function_type(),
    )


async def _anchor(
    resolver: InventoryImpactAnchorResolver, context: FunctionInvocationContext
) -> str:
    if context.purposes != (DECISION_PURPOSE,):
        raise PermissionError("decision function purpose does not match invocation context")
    target_ref = await resolver.resolve(context)
    if target_ref is None:
        raise LookupError("authenticated decision target anchor is unavailable")
    return target_ref


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision evidence observation time MUST be timezone-aware")


def _tier(value: int, upper_bounds: tuple[int, ...]) -> str:
    for name, bound in zip(_TIERS, upper_bounds, strict=False):
        if value <= bound:
            return name
    return _TIERS[-1]


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." not in text else text.rstrip("0").rstrip(".")


def _result(
    *,
    function: str,
    target_ref: str,
    tier: str,
    complete: bool,
    gate_satisfied: bool | None,
    observed_at: datetime,
    reasons: list[str],
    extra: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "1.0.0",
        "function": function,
        "target_ref": target_ref,
        "tier": tier,
        "complete": complete,
        "observed_at": observed_at.isoformat(),
        "reason_codes": sorted(reasons),
        "execution_authority": False,
        "mutation_authority": False,
        **extra,
    }
    if gate_satisfied is not None:
        result["gate_satisfied"] = gate_satisfied
    return result


def _tier_schema(values: tuple[str, ...]) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}


def _output_schema(
    *, tier_values: tuple[str, ...], extra: dict[str, object], gated: bool = True
) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": {"const": "1.0.0"},
        "function": {"type": "string"},
        "target_ref": {"type": "string"},
        "tier": {"type": "string", "enum": list(tier_values)},
        "complete": {"type": "boolean"},
        "observed_at": {"type": "string"},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "execution_authority": {"const": False},
        "mutation_authority": {"const": False},
    }
    properties = {**base, **extra}
    if gated:
        properties["gate_satisfied"] = {"type": "boolean"}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


def _declaration(
    name: str,
    properties: dict[str, object],
    required: list[str],
    output_schema: dict[str, object],
) -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
        },
        output_schema=output_schema,
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[DECISION_PURPOSE],
        timeout_seconds=5,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=65_536,
        network_allowed=False,
        credentials_allowed=False,
    )


__all__ = [
    "BLAST_RADIUS_FUNCTION_NAME",
    "CHANGE_RISK_FUNCTION_NAME",
    "COST_OF_DELAY_FUNCTION_NAME",
    "DECISION_PURPOSE",
    "BlastRadiusEvidence",
    "BlastRadiusEvidenceReader",
    "ChangeRiskEvidence",
    "ChangeRiskEvidenceReader",
    "CostOfDelayEvidence",
    "CostOfDelayEvidenceReader",
    "ImpactedResource",
    "assess_blast_radius",
    "assess_change_risk",
    "assess_cost_of_delay",
    "blast_radius_function",
    "blast_radius_function_type",
    "change_risk_function",
    "change_risk_function_type",
    "cost_of_delay_function",
    "cost_of_delay_function_type",
    "decision_function_types",
]
