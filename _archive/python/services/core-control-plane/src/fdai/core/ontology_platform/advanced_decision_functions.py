"""Advanced ontology decision FunctionTypes and Merkle DAG composition runner (Items 7-11).

Provides:
7. ``decision.slo_exhaustion_eta``: error-budget time-to-exhaustion (minutes) from SLO burn rate.
8. ``decision.change_collision``: active concurrent change/process collision detection in a
   dependency subgraph.
9. ``decision.recovery_feasibility``: RTO/RPO feasibility of a ``RecoveryPlan`` against its
   ``RecoveryObjective``.
10. ``decision.spof_exposure``: single-point-of-failure topological exposure scoring.
11. ``OntologyFunctionDagRunner``: topological execution of chained ontology functions with a
    Merkle-root receipt digest over all step invocation receipts.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Final

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)

from .decision_functions import DECISION_PURPOSE
from .finops_value_modeling import budget_burn_risk_function_type
from .functions import (
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunctionRegistry,
)

SLO_EXHAUSTION_ETA_FUNCTION_NAME: Final = "decision.slo_exhaustion_eta"
CHANGE_COLLISION_FUNCTION_NAME: Final = "decision.change_collision"
RECOVERY_FEASIBILITY_FUNCTION_NAME: Final = "decision.recovery_feasibility"
SPOF_EXPOSURE_FUNCTION_NAME: Final = "decision.spof_exposure"

_SPOF_TIERS: Final = ("none", "low", "medium", "high", "critical")
_SPOF_RANK: Final = {name: idx for idx, name in enumerate(_SPOF_TIERS)}


@dataclass(frozen=True, slots=True)
class SloExhaustionEvidence:
    """Item 7: Observed error-budget fraction remaining and current burn rate."""

    remaining_budget_ratio: float | None
    burn_rate_per_hour: float | None
    window_hours: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeCollisionEvidence:
    """Item 8: Active changes or processes touching the target's dependency subgraph."""

    active_change_refs: tuple[str, ...]
    active_process_refs: tuple[str, ...]
    subgraph_complete: bool
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryFeasibilityEvidence:
    """Item 9: Observed recovery rehearsal metrics vs RecoveryObjective targets."""

    estimated_rto_minutes: float | None
    target_rto_minutes: float | None
    estimated_rpo_minutes: float | None
    target_rpo_minutes: float | None
    rehearsal_verified: bool | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class SpofExposureEvidence:
    """Item 10: Topological redundancy and backup posture for one Resource."""

    zone_redundant: bool | None
    backup_verified: bool | None
    alternate_path_count: int | None
    critical_dependent_count: int | None
    observed_at: datetime


def assess_slo_exhaustion_eta(
    evidence: SloExhaustionEvidence,
    *,
    target_ref: str,
    min_remaining_minutes: int,
) -> dict[str, object]:
    """Item 7: Compute error-budget exhaustion ETA in minutes and gate on safety margin."""

    if min_remaining_minutes < 1:
        raise ValueError("min_remaining_minutes MUST be positive")
    reasons: list[str] = []
    rem = evidence.remaining_budget_ratio
    burn = evidence.burn_rate_per_hour
    if rem is None or not isfinite(rem) or not 0.0 <= rem <= 1.0:
        reasons.append("remaining_budget_unobserved")
    if burn is None or not isfinite(burn) or burn < 0.0:
        reasons.append("burn_rate_unobserved")
    complete = not reasons
    eta_minutes: float | None = None
    if complete and rem is not None and burn is not None:
        if burn == 0.0:
            eta_minutes = float(evidence.window_hours * 60 * 10)
        else:
            eta_minutes = round((rem / burn) * 60.0, 2)
    satisfied = complete and eta_minutes is not None and eta_minutes >= float(min_remaining_minutes)
    tier = (
        "unknown"
        if not complete or eta_minutes is None
        else ("critical" if eta_minutes < 60 else ("high" if eta_minutes < 240 else "low"))
    )
    return _envelope(
        function=SLO_EXHAUSTION_ETA_FUNCTION_NAME,
        target_ref=target_ref,
        tier=tier,
        complete=complete,
        gate_satisfied=satisfied,
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={"eta_minutes": eta_minutes, "min_remaining_minutes": min_remaining_minutes},
    )


def assess_change_collision(
    evidence: ChangeCollisionEvidence,
    *,
    target_ref: str,
    max_collisions: int = 0,
) -> dict[str, object]:
    """Item 8: Detect concurrent changes or processes in the dependency subgraph."""

    if max_collisions < 0:
        raise ValueError("max_collisions MUST be non-negative")
    reasons: list[str] = []
    if not evidence.subgraph_complete:
        reasons.append("subgraph_incomplete")
    complete = not reasons
    collisions = sorted(set(evidence.active_change_refs) | set(evidence.active_process_refs))
    count = len(collisions)
    tier = (
        "unknown"
        if not complete
        else ("low" if count == 0 else ("high" if count == 1 else "critical"))
    )
    return _envelope(
        function=CHANGE_COLLISION_FUNCTION_NAME,
        target_ref=target_ref,
        tier=tier,
        complete=complete,
        gate_satisfied=complete and count <= max_collisions,
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={"collision_count": count, "colliding_refs": collisions},
    )


def assess_recovery_feasibility(
    evidence: RecoveryFeasibilityEvidence,
    *,
    target_ref: str,
) -> dict[str, object]:
    """Item 9: Verify whether a RecoveryPlan meets its RecoveryObjective RTO and RPO."""

    reasons: list[str] = []
    for name, val in (
        ("estimated_rto_unobserved", evidence.estimated_rto_minutes),
        ("target_rto_unobserved", evidence.target_rto_minutes),
        ("estimated_rpo_unobserved", evidence.estimated_rpo_minutes),
        ("target_rpo_unobserved", evidence.target_rpo_minutes),
    ):
        if val is None or not isfinite(val) or val < 0.0:
            reasons.append(name)
    if evidence.rehearsal_verified is None:
        reasons.append("rehearsal_unobserved")
    complete = not reasons
    rto_ok = (
        complete
        and evidence.estimated_rto_minutes is not None
        and evidence.target_rto_minutes is not None
        and evidence.estimated_rto_minutes <= evidence.target_rto_minutes
    )
    rpo_ok = (
        complete
        and evidence.estimated_rpo_minutes is not None
        and evidence.target_rpo_minutes is not None
        and evidence.estimated_rpo_minutes <= evidence.target_rpo_minutes
    )
    feasible = bool(rto_ok and rpo_ok and evidence.rehearsal_verified is True)
    return _envelope(
        function=RECOVERY_FEASIBILITY_FUNCTION_NAME,
        target_ref=target_ref,
        tier="unknown" if not complete else ("feasible" if feasible else "infeasible"),
        complete=complete,
        gate_satisfied=feasible,
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={"rto_satisfied": rto_ok, "rpo_satisfied": rpo_ok},
    )


def assess_spof_exposure(
    evidence: SpofExposureEvidence,
    *,
    target_ref: str,
    max_tier: str,
) -> dict[str, object]:
    """Item 10: Quantify single-point-of-failure exposure from redundancy and backup facts."""

    if max_tier not in _SPOF_RANK:
        raise ValueError(f"Unsupported SPOF max_tier: {max_tier!r}")
    reasons: list[str] = []
    if evidence.zone_redundant is None:
        reasons.append("zone_redundancy_unobserved")
    if evidence.backup_verified is None:
        reasons.append("backup_unobserved")
    if evidence.alternate_path_count is None or evidence.alternate_path_count < 0:
        reasons.append("alternate_paths_unobserved")
    if evidence.critical_dependent_count is None or evidence.critical_dependent_count < 0:
        reasons.append("critical_dependents_unobserved")
    complete = not reasons
    points = 0
    if complete:
        if not evidence.zone_redundant:
            points += 2
        if not evidence.backup_verified:
            points += 2
        if (evidence.alternate_path_count or 0) == 0:
            points += 2
        if (evidence.critical_dependent_count or 0) > 0 and points > 0:
            points += 2
    tier = (
        "unknown"
        if not complete
        else (
            "none"
            if points == 0
            else "low"
            if points <= 2
            else "medium"
            if points <= 4
            else "high"
            if points <= 6
            else "critical"
        )
    )
    satisfied = complete and _SPOF_RANK[tier] <= _SPOF_RANK[max_tier]
    return _envelope(
        function=SPOF_EXPOSURE_FUNCTION_NAME,
        target_ref=target_ref,
        tier=tier,
        complete=complete,
        gate_satisfied=satisfied,
        observed_at=evidence.observed_at,
        reasons=reasons,
        extra={"exposure_points": points},
    )


def slo_exhaustion_eta_function_type() -> OntologyFunctionType:
    return _decl(
        SLO_EXHAUSTION_ETA_FUNCTION_NAME,
        {"min_remaining_minutes": {"type": "integer", "minimum": 1, "maximum": 100_800}},
        ["min_remaining_minutes"],
        ("low", "high", "critical", "unknown"),
        {
            "eta_minutes": {"type": ["number", "null"]},
            "min_remaining_minutes": {"type": "integer"},
        },
    )


def change_collision_function_type() -> OntologyFunctionType:
    return _decl(
        CHANGE_COLLISION_FUNCTION_NAME,
        {"max_collisions": {"type": "integer", "minimum": 0, "maximum": 100}},
        ["max_collisions"],
        ("low", "high", "critical", "unknown"),
        {
            "collision_count": {"type": "integer", "minimum": 0},
            "colliding_refs": {"type": "array", "items": {"type": "string"}},
        },
    )


def recovery_feasibility_function_type() -> OntologyFunctionType:
    return _decl(
        RECOVERY_FEASIBILITY_FUNCTION_NAME,
        {},
        [],
        ("feasible", "infeasible", "unknown"),
        {
            "rto_satisfied": {"type": "boolean"},
            "rpo_satisfied": {"type": "boolean"},
        },
    )


def spof_exposure_function_type() -> OntologyFunctionType:
    return _decl(
        SPOF_EXPOSURE_FUNCTION_NAME,
        {"max_tier": {"type": "string", "enum": list(_SPOF_TIERS[:-1])}},
        ["max_tier"],
        (*_SPOF_TIERS, "unknown"),
        {"exposure_points": {"type": "integer", "minimum": 0}},
    )


def advanced_decision_function_types() -> tuple[OntologyFunctionType, ...]:
    return (
        slo_exhaustion_eta_function_type(),
        change_collision_function_type(),
        recovery_feasibility_function_type(),
        spof_exposure_function_type(),
        budget_burn_risk_function_type(),
    )


@dataclass(frozen=True, slots=True)
class FunctionDagNode:
    """Item 11: One node in a chained OntologyFunction DAG."""

    node_id: str
    function_name: str
    depends_on: tuple[str, ...] = ()
    static_arguments: Mapping[str, Any] | None = None
    argument_builder: Callable[[Mapping[str, object]], Mapping[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class DagExecutionReceipt:
    """Item 11: Combined output and Merkle-chained receipt across a function DAG."""

    ordered_node_ids: tuple[str, ...]
    outputs: Mapping[str, object]
    receipts: Mapping[str, FunctionInvocationReceipt]
    merkle_root_digest: str


class OntologyFunctionDagRunner:
    """Item 11: Execute a DAG of OntologyFunctions and bind a Merkle receipt digest."""

    def __init__(self, registry: OntologyFunctionRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        nodes: tuple[FunctionDagNode, ...],
        *,
        context: FunctionInvocationContext,
    ) -> DagExecutionReceipt:
        if not nodes or len({n.node_id for n in nodes}) != len(nodes):
            raise ValueError("DAG nodes MUST be non-empty and unique")
        ordered = _topological_order(nodes)
        outputs: dict[str, object] = {}
        receipts: dict[str, FunctionInvocationReceipt] = {}
        chain_acc = "sha256:" + "0" * 64
        for node in ordered:
            args = (
                dict(node.argument_builder(outputs))
                if node.argument_builder is not None
                else dict(node.static_arguments or {})
            )
            result, receipt = await self._registry.invoke_with_receipt(
                node.function_name, args, context=context
            )
            outputs[node.node_id] = result
            receipts[node.node_id] = receipt
            chain_acc = content_digest(
                {
                    "parent_merkle": chain_acc,
                    "node_id": node.node_id,
                    "invocation_id": receipt.invocation_id,
                    "input_digest": receipt.input_digest,
                    "output_digest": receipt.output_digest,
                }
            )
        return DagExecutionReceipt(
            ordered_node_ids=tuple(n.node_id for n in ordered),
            outputs=outputs,
            receipts=receipts,
            merkle_root_digest=chain_acc,
        )


def _topological_order(nodes: tuple[FunctionDagNode, ...]) -> tuple[FunctionDagNode, ...]:
    by_id = {n.node_id: n for n in nodes}
    in_degree: dict[str, int] = {n.node_id: 0 for n in nodes}
    children: dict[str, list[str]] = {n.node_id: [] for n in nodes}
    for node in nodes:
        for dep in node.depends_on:
            if dep not in by_id:
                raise ValueError(f"Unknown DAG dependency {dep!r} on node {node.node_id!r}")
            in_degree[node.node_id] += 1
            children[dep].append(node.node_id)
    ready = deque(sorted(nid for nid, deg in in_degree.items() if deg == 0))
    ordered: list[FunctionDagNode] = []
    while ready:
        nid = ready.popleft()
        ordered.append(by_id[nid])
        for child in sorted(children[nid]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                ready.append(child)
    if len(ordered) != len(nodes):
        raise ValueError("OntologyFunction DAG contains a cycle")
    return tuple(ordered)


def _envelope(
    *,
    function: str,
    target_ref: str,
    tier: str,
    complete: bool,
    gate_satisfied: bool,
    observed_at: datetime,
    reasons: list[str],
    extra: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "function": function,
        "target_ref": target_ref,
        "tier": tier,
        "complete": complete,
        "gate_satisfied": gate_satisfied,
        "observed_at": observed_at.isoformat(),
        "reason_codes": sorted(reasons),
        "execution_authority": False,
        "mutation_authority": False,
        **extra,
    }


def _decl(
    name: str,
    input_props: dict[str, object],
    required_inputs: list[str],
    tier_values: tuple[str, ...],
    extra_outputs: dict[str, object],
) -> OntologyFunctionType:
    base_out: dict[str, object] = {
        "schema_version": {"const": "1.0.0"},
        "function": {"type": "string"},
        "target_ref": {"type": "string"},
        "tier": {"type": "string", "enum": list(tier_values)},
        "complete": {"type": "boolean"},
        "gate_satisfied": {"type": "boolean"},
        "observed_at": {"type": "string"},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "execution_authority": {"const": False},
        "mutation_authority": {"const": False},
        **extra_outputs,
    }
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": required_inputs,
            "properties": input_props,
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": sorted(base_out),
            "properties": base_out,
        },
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
    "CHANGE_COLLISION_FUNCTION_NAME",
    "RECOVERY_FEASIBILITY_FUNCTION_NAME",
    "SLO_EXHAUSTION_ETA_FUNCTION_NAME",
    "SPOF_EXPOSURE_FUNCTION_NAME",
    "ChangeCollisionEvidence",
    "DagExecutionReceipt",
    "FunctionDagNode",
    "OntologyFunctionDagRunner",
    "RecoveryFeasibilityEvidence",
    "SloExhaustionEvidence",
    "SpofExposureEvidence",
    "advanced_decision_function_types",
    "assess_change_collision",
    "assess_recovery_feasibility",
    "assess_slo_exhaustion_eta",
    "assess_spof_exposure",
    "change_collision_function_type",
    "recovery_feasibility_function_type",
    "slo_exhaustion_eta_function_type",
    "spof_exposure_function_type",
]
