"""Tests for Area F (Items 26-30): Staging parity, Wave 5 safety, auto-settler, and parity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.core.measurement.closed_loop_governance import (
    PostWindowValueClaimAutoSettler,
    SreAgentParityCase,
    StagingParityEvidence,
    WorkflowScaleSafetyController,
    evaluate_sre_agent_parity_cohort,
    recalibrate_option_utility_from_settlement,
    verify_action_staging_parity,
)
from fdai.core.measurement.value_claim import (
    CohortRole,
    ObservationLane,
    ValueClaimDeclaration,
    ValueClaimStatus,
    ValueCohortObservation,
    ValueDirection,
    ValueUnit,
    settle_value_claim,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_item26_staging_parity_verification() -> None:
    matched = verify_action_staging_parity(
        StagingParityEvidence(
            action_type_ref="ops.scale-in",
            staging_run_id="stg-1",
            expected_state_delta={"replicas": 3, "healthy": True},
            staging_observed_delta={"replicas": 3, "healthy": True},
            rollback_rehearsed=True,
            policy_escape_count=0,
            observed_at=NOW,
        )
    )
    assert matched.parity_verified is True
    assert matched.mismatched_keys == ()

    drifted = verify_action_staging_parity(
        StagingParityEvidence(
            action_type_ref="ops.scale-in",
            staging_run_id="stg-2",
            expected_state_delta={"replicas": 3},
            staging_observed_delta={"replicas": 2},
            rollback_rehearsed=False,
            policy_escape_count=0,
            observed_at=NOW,
        )
    )
    assert drifted.parity_verified is False
    assert drifted.mismatched_keys == ("replicas",)
    assert set(drifted.reason_codes) == {"state_delta_mismatch", "rollback_not_rehearsed"}


async def test_item27_wave5_distributed_lock_backpressure_sli_and_auto_demotion() -> None:
    store = InMemoryStateStore()
    ctrl = WorkflowScaleSafetyController(store, max_active_per_scope=2, max_failure_rate=0.10)

    ok1, reason1 = await ctrl.acquire_target_and_scope(
        scope_ref="scope-a", target_resource_ref="vm-1", process_id="p-1"
    )
    assert (ok1, reason1) == (True, None)

    # Same target locked by p-1 -> rejected
    dup, dup_reason = await ctrl.acquire_target_and_scope(
        scope_ref="scope-a", target_resource_ref="vm-1", process_id="p-2"
    )
    assert (dup, dup_reason) == (False, "target_distributed_lock_held")

    ok2, _ = await ctrl.acquire_target_and_scope(
        scope_ref="scope-a", target_resource_ref="vm-2", process_id="p-2"
    )
    assert ok2 is True

    # 3rd concurrent in scope-a exceeds max_active_per_scope=2
    bp, bp_reason = await ctrl.acquire_target_and_scope(
        scope_ref="scope-a", target_resource_ref="vm-3", process_id="p-3"
    )
    assert (bp, bp_reason) == (False, "scope_backpressure_limit_reached")

    await ctrl.release_target_and_scope(
        scope_ref="scope-a", target_resource_ref="vm-2", process_id="p-2"
    )

    sli, demotion = ctrl.evaluate_sli_and_demotion(
        workflow_name="change-risk-gated-scale-in",
        current_mode=Mode.ENFORCE,
        succeeded_runs=7,
        failed_runs=2,
        rolled_back_runs=1,
        policy_escape_count=0,
    )
    assert sli.failure_or_rollback_rate == 0.3
    assert demotion.demoted is True
    assert demotion.effective_mode is Mode.SHADOW
    assert "failure_or_rollback_rate_breach" in demotion.reason_codes


async def test_items_28_29_auto_settler_and_learning_utility_recalibration() -> None:
    store = InMemoryStateStore()
    settler = PostWindowValueClaimAutoSettler(store)

    mature_decl = ValueClaimDeclaration(
        claim_id="claim-mature",
        workflow_ref="predictive-scale",
        workflow_version="1.0.0",
        objective_ref="obj-1",
        metric_name="mttr",
        unit=ValueUnit.DURATION_SECONDS,
        direction=ValueDirection.DECREASE_IS_BETTER,
        target_value=Decimal("300"),
        scenario_set_version="v1",
        window_start=NOW - timedelta(days=14),
        window_end=NOW - timedelta(hours=1),
        min_samples_per_cohort=5,
    )
    immature_decl = mature_decl.model_copy(
        update={"claim_id": "claim-open", "window_end": NOW + timedelta(days=2)}
    )
    base_c = ValueCohortObservation(
        role=CohortRole.BASELINE,
        lane=ObservationLane.INDEPENDENT_OBSERVATION,
        scenario_set_version="v1",
        complete=True,
        samples=tuple(Decimal(v) for v in ("600", "610", "590", "605", "595", "600")),
        evidence_refs=("ev:b",),
        observed_at=NOW,
    )
    treat_c = ValueCohortObservation(
        role=CohortRole.TREATMENT,
        lane=ObservationLane.INDEPENDENT_OBSERVATION,
        scenario_set_version="v1",
        complete=True,
        samples=tuple(Decimal(v) for v in ("290", "300", "295", "305", "290", "300")),
        evidence_refs=("ev:t",),
        observed_at=NOW,
    )

    batch = await settler.run_tick(
        ((mature_decl, (base_c, treat_c)), (immature_decl, (base_c, treat_c))),
        now=NOW,
    )
    assert len(batch.settled) == 1
    assert batch.settled[0].status is ValueClaimStatus.IMPROVED
    assert batch.deferred_claim_ids == ("claim-open",)

    recalibrated = recalibrate_option_utility_from_settlement(
        option_id="opt-1",
        prior_utility=0.75,
        prior_confidence=0.80,
        expected_improvement_per_event=Decimal("250"),
        settlement=batch.settled[0],
    )
    assert recalibrated.hold_for_review is False
    assert recalibrated.updated_confidence == 0.85
    assert recalibrated.reason_code == "verified_improvement_boost"

    regressed = settle_value_claim(
        mature_decl,
        (
            treat_c.model_copy(update={"role": CohortRole.BASELINE}),
            base_c.model_copy(update={"role": CohortRole.TREATMENT}),
        ),
    )
    demoted_opt = recalibrate_option_utility_from_settlement(
        option_id="opt-1",
        prior_utility=0.75,
        prior_confidence=0.80,
        expected_improvement_per_event=Decimal("250"),
        settlement=regressed,
    )
    assert demoted_opt.hold_for_review is True
    assert demoted_opt.reason_code == "regression_demotion"


def test_item30_sre_agent_parity_cohort_evaluation() -> None:
    cohort = (
        SreAgentParityCase(
            case_id="inc-1",
            ground_truth_cause_ref="res-db",
            should_abstain=False,
            fdai_cause_ref="res-db",
            fdai_abstained=False,
            fdai_citations_valid=True,
            peer_cause_ref="res-db",
            peer_abstained=False,
            peer_citations_valid=True,
        ),
        SreAgentParityCase(
            case_id="inc-2-incomplete",
            ground_truth_cause_ref=None,
            should_abstain=True,
            fdai_cause_ref=None,
            fdai_abstained=True,
            fdai_citations_valid=True,
            peer_cause_ref="res-guessed",
            peer_abstained=False,
            peer_citations_valid=False,
        ),
    )
    report = evaluate_sre_agent_parity_cohort(cohort)
    assert report.fdai_accuracy == 1.0
    assert report.peer_accuracy == 0.5
    assert report.fdai_safe_abstention_rate == 1.0
    assert report.peer_safe_abstention_rate == 0.0
    assert report.parity_satisfied is True
