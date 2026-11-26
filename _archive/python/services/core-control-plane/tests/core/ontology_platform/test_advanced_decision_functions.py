"""Tests for Area B (Items 7-11): Advanced decision functions and Merkle DAG runner."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.ontology_platform.advanced_decision_functions import (
    CHANGE_COLLISION_FUNCTION_NAME,
    SLO_EXHAUSTION_ETA_FUNCTION_NAME,
    ChangeCollisionEvidence,
    FunctionDagNode,
    OntologyFunctionDagRunner,
    RecoveryFeasibilityEvidence,
    SloExhaustionEvidence,
    SpofExposureEvidence,
    advanced_decision_function_types,
    assess_change_collision,
    assess_recovery_feasibility,
    assess_slo_exhaustion_eta,
    assess_spof_exposure,
    change_collision_function_type,
    slo_exhaustion_eta_function_type,
)
from fdai.core.ontology_platform.decision_functions import DECISION_PURPOSE
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_item7_slo_exhaustion_eta_calculates_minutes_and_gates() -> None:
    healthy = assess_slo_exhaustion_eta(
        SloExhaustionEvidence(
            remaining_budget_ratio=0.5,
            burn_rate_per_hour=0.05,
            window_hours=720,
            observed_at=NOW,
        ),
        target_ref="svc-1",
        min_remaining_minutes=120,
    )
    assert healthy["eta_minutes"] == 600.0
    assert healthy["gate_satisfied"] is True

    urgent = assess_slo_exhaustion_eta(
        SloExhaustionEvidence(
            remaining_budget_ratio=0.1,
            burn_rate_per_hour=0.2,
            window_hours=720,
            observed_at=NOW,
        ),
        target_ref="svc-1",
        min_remaining_minutes=60,
    )
    assert urgent["eta_minutes"] == 30.0
    assert urgent["tier"] == "critical"
    assert urgent["gate_satisfied"] is False


def test_item8_change_collision_blocks_when_active_changes_exist() -> None:
    clear = assess_change_collision(
        ChangeCollisionEvidence((), (), subgraph_complete=True, observed_at=NOW),
        target_ref="res-1",
        max_collisions=0,
    )
    assert clear["collision_count"] == 0
    assert clear["gate_satisfied"] is True

    colliding = assess_change_collision(
        ChangeCollisionEvidence(("chg-1",), ("proc-2",), subgraph_complete=True, observed_at=NOW),
        target_ref="res-1",
        max_collisions=0,
    )
    assert colliding["collision_count"] == 2
    assert colliding["tier"] == "critical"
    assert colliding["gate_satisfied"] is False


def test_item9_recovery_feasibility_verifies_rto_rpo_and_rehearsal() -> None:
    ok = assess_recovery_feasibility(
        RecoveryFeasibilityEvidence(
            estimated_rto_minutes=12.0,
            target_rto_minutes=15.0,
            estimated_rpo_minutes=3.0,
            target_rpo_minutes=5.0,
            rehearsal_verified=True,
            observed_at=NOW,
        ),
        target_ref="res-1",
    )
    assert ok["tier"] == "feasible"
    assert ok["gate_satisfied"] is True

    breach = assess_recovery_feasibility(
        RecoveryFeasibilityEvidence(
            estimated_rto_minutes=25.0,
            target_rto_minutes=15.0,
            estimated_rpo_minutes=3.0,
            target_rpo_minutes=5.0,
            rehearsal_verified=True,
            observed_at=NOW,
        ),
        target_ref="res-1",
    )
    assert breach["tier"] == "infeasible"
    assert breach["gate_satisfied"] is False


def test_item10_spof_exposure_scores_redundancy_and_backup_gaps() -> None:
    resilient = assess_spof_exposure(
        SpofExposureEvidence(
            zone_redundant=True,
            backup_verified=True,
            alternate_path_count=2,
            critical_dependent_count=3,
            observed_at=NOW,
        ),
        target_ref="res-1",
        max_tier="low",
    )
    assert resilient["tier"] == "none"
    assert resilient["gate_satisfied"] is True

    exposed = assess_spof_exposure(
        SpofExposureEvidence(
            zone_redundant=False,
            backup_verified=False,
            alternate_path_count=0,
            critical_dependent_count=2,
            observed_at=NOW,
        ),
        target_ref="res-1",
        max_tier="medium",
    )
    assert exposed["tier"] == "critical"
    assert exposed["gate_satisfied"] is False


async def test_item11_ontology_function_dag_runner_chains_outputs_with_merkle_digest() -> None:
    decls = advanced_decision_function_types()
    release = build_ontology_release(function_types=decls)
    registry = OntologyFunctionRegistry(release=release)

    async def _slo_fn(args: Mapping[str, Any], _ctx: FunctionInvocationContext) -> object:
        return assess_slo_exhaustion_eta(
            SloExhaustionEvidence(0.5, 0.05, 720, NOW),
            target_ref="res-1",
            min_remaining_minutes=int(args["min_remaining_minutes"]),
        )

    async def _collision_fn(args: Mapping[str, Any], _ctx: FunctionInvocationContext) -> object:
        return assess_change_collision(
            ChangeCollisionEvidence((), (), True, NOW),
            target_ref="res-1",
            max_collisions=int(args["max_collisions"]),
        )

    registry.register_contextual(slo_exhaustion_eta_function_type(), _slo_fn)
    registry.register_contextual(change_collision_function_type(), _collision_fn)

    runner = OntologyFunctionDagRunner(registry)
    nodes = (
        FunctionDagNode(
            node_id="collision",
            function_name=CHANGE_COLLISION_FUNCTION_NAME,
            depends_on=("slo",),
            argument_builder=lambda outs: {
                "max_collisions": 0 if outs["slo"]["gate_satisfied"] else 1  # type: ignore[index]
            },
        ),
        FunctionDagNode(
            node_id="slo",
            function_name=SLO_EXHAUSTION_ETA_FUNCTION_NAME,
            static_arguments={"min_remaining_minutes": 120},
        ),
    )
    ctx = FunctionInvocationContext(caller_agent="WorkflowGate", purposes=(DECISION_PURPOSE,))
    dag_receipt = await runner.execute(nodes, context=ctx)

    assert dag_receipt.ordered_node_ids == ("slo", "collision")
    assert dag_receipt.merkle_root_digest.startswith("sha256:")
    assert set(dag_receipt.receipts) == {"slo", "collision"}

    # Cycle detection
    cyclic = (
        FunctionDagNode("a", SLO_EXHAUSTION_ETA_FUNCTION_NAME, depends_on=("b",)),
        FunctionDagNode("b", CHANGE_COLLISION_FUNCTION_NAME, depends_on=("a",)),
    )
    with pytest.raises(ValueError, match="cycle"):
        await runner.execute(cyclic, context=ctx)
