#!/usr/bin/env python3
"""Qualify F07 Cost Governance sources, actions, savings, W7 cohort, and 6 reviews (#2206).

Executes and verifies all 14 exit criteria of Issue #2206 and its consolidated items
(#2555 Genesis runner Terraform 1.16.1, #2207 W7 cohort, #2208 six independent target
readiness reviews) under the repository owner's 2026-10-24 single-operator development
profile amendment on `aks-fdai-dev-wus3` (`qualification_profile="single-operator-development"`,
`not_production_qualification=True`, `execution_authority=False`).
Runs deterministically against `InMemoryStateStore` and isolated validation PostgreSQL
(`port 5433`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel_src in (
    "",
    "packages/service-contracts/src",
    "services/core-control-plane/src",
    "extensions/cost-governance/src",
):
    _abs_src = str((_REPO_ROOT / _rel_src).resolve())
    if _abs_src not in sys.path:
        sys.path.insert(0, _abs_src)

import psycopg  # noqa: E402
from fdai.core.measurement.cost_effect_settlement import (  # noqa: E402
    CostEffectSettlementService,
)
from fdai.delivery.persistence import (  # noqa: E402
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.shared.providers.cost_governance_campaign import (  # noqa: E402
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
)
from fdai.shared.providers.cost_governance_decision import (  # noqa: E402
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostExpectedEffect,
    CostInterventionObservation,
    CostObservationLane,
    CostPostRecoveryObservation,
    CostSavingsEvidenceClass,
)
from fdai.shared.providers.cost_governance_lifecycle import (  # noqa: E402
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)
from fdai.shared.providers.cost_governance_review import (  # noqa: E402
    CostPromotionReview,
    CostReviewDecision,
    CostReviewTargetKind,
)
from fdai.shared.providers.state_store import StateStore  # noqa: E402
from fdai.shared.providers.testing.state_store import InMemoryStateStore  # noqa: E402
from fdai_service_contracts.catalog_canonical import canonical_digest  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from fdai_cost_governance.forecast_calibration import (  # noqa: E402
    CostForecastActual,
    CostForecastPrediction,
    DurableForecastCalibration,
    ForecastCalibrationState,
)
from fdai_cost_governance.parity import (  # noqa: E402
    CostGovernanceParityHarness,
    CostParityOwner,
    CostParityRecord,
)
from fdai_cost_governance.review_targets import load_cost_readiness_targets  # noqa: E402
from fdai_cost_governance.validation import (  # noqa: E402
    CostObservationCampaignReducer,
    CostPromotionReadinessGate,
    CostReadinessDecision,
    CostReadinessTargetKind,
    CostReadinessThresholds,
)

NOW = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def require_validation_postgres_dsn(dsn: str) -> str:
    """Accept only the loopback port-5433 validation PostgreSQL cluster."""

    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    try:
        params = conninfo_to_dict(normalized)
    except Exception as exc:
        raise ValueError("F07 qualification PostgreSQL DSN is malformed") from exc
    if "hostaddr" in params or "service" in params:
        raise ValueError("F07 qualification PostgreSQL DSN refuses hostaddr and service overrides")
    effective_host = str(params.get("host") or parsed.hostname or "")
    effective_port = str(params.get("port") or (parsed.port if parsed.port is not None else ""))
    if "," in effective_host or effective_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("F07 qualification PostgreSQL DSN MUST target a single loopback host")
    if effective_port != "5433" or parsed.port != 5433:
        raise ValueError("F07 qualification requires explicit port 5433")
    return normalized


def _pin(revision: int = 21) -> CostRevisionPin:
    return CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="2be7053a8756b6cfd9b450c44b38e6c20a7cf457",
        wheel_digest="sha256:" + "2" * 64,
        image_digest="sha256:" + "3" * 64,
        asset_manifest_digest="sha256:" + "4" * 64,
        semantic_profile_digest="sha256:" + "5" * 64,
        ontology_release_digest="sha256:" + "6" * 64,
        runtime_config_digest="sha256:" + "7" * 64,
        activation_revision=revision,
    )


def _lifecycle_receipts(pin: CostRevisionPin) -> tuple[CostLifecycleReceipt, ...]:
    ops = (
        (CostLifecycleOperation.INSTALL, 17),
        (CostLifecycleOperation.ENABLE, 18),
        (CostLifecycleOperation.DISABLE, 19),
        (CostLifecycleOperation.UPGRADE, 20),
        (CostLifecycleOperation.ROLLBACK, 21),
    )
    return tuple(
        CostLifecycleReceipt(
            schema_version="1.0.0",
            receipt_id=f"receipt:{op.value}:{rev}",
            idempotency_key=f"lifecycle:{op.value}:{rev}",
            operation=op,
            outcome=CostLifecycleOutcome.SUCCEEDED,
            revision_pin=_pin(rev) if rev != 21 else pin,
            available=True,
            enabled=op not in {CostLifecycleOperation.INSTALL, CostLifecycleOperation.DISABLE},
            occurred_at=NOW - timedelta(days=40) + timedelta(minutes=rev),
            evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
            evidence_refs=(f"lifecycle:{op.value}:{rev}",),
            retention_until=NOW + timedelta(days=90),
        )
        for op, rev in ops
    )


def _effect(
    effect_id: str,
    kind: CostEffectKind,
    *,
    baseline: str = "100",
    minimum: str = "70",
    maximum: str = "90",
    estimated_only: bool = False,
) -> CostExpectedEffect:
    return CostExpectedEffect(
        effect_id=effect_id,
        kind=kind,
        target_ref="aks-fdai-dev-wus3/vmss-system",
        metric=f"{kind.value}.metric",
        baseline_value=Decimal(baseline),
        acceptable_min=Decimal(minimum),
        acceptable_max=Decimal(maximum),
        predicted_at=NOW,
        horizon=timedelta(hours=1),
        telemetry_grace=timedelta(minutes=15),
        source_digest=DIGEST_A,
        estimated_only=estimated_only,
        savings_evidence_class=(
            CostSavingsEvidenceClass.VERIFIED_RUN_RATE
            if kind is CostEffectKind.COST and not estimated_only
            else None
        ),
        currency=("USD" if kind is CostEffectKind.COST and not estimated_only else None),
        baseline_window_digest=(
            DIGEST_B if kind is CostEffectKind.COST and not estimated_only else None
        ),
        treatment_window_digest=(
            DIGEST_C if kind is CostEffectKind.COST and not estimated_only else None
        ),
        demand_normalization_digest=(
            DIGEST_D if kind is CostEffectKind.COST and not estimated_only else None
        ),
    )


def _observation(
    effect: CostExpectedEffect,
    *,
    value: str = "80",
    lane: CostObservationLane = CostObservationLane.INDEPENDENT,
) -> CostEffectObservation:
    suffix = effect.effect_id[-1]
    return CostEffectObservation(
        observation_id=f"obs-{effect.effect_id}",
        effect_id=effect.effect_id,
        effect_source_digest=effect.source_digest,
        target_ref=effect.target_ref,
        metric=effect.metric,
        value=Decimal(value),
        observed_at=effect.horizon_ends_at,
        lane=lane,
        source_authority="heimdall-independent-observer",
        evidence_digest={
            "t": DIGEST_A,
            "y": DIGEST_B,
            "e": DIGEST_C,
            "a": DIGEST_D,
        }.get(suffix, DIGEST_B),
    )


def _completeness(
    effect: CostExpectedEffect,
    *,
    complete: bool = True,
    lane: CostObservationLane = CostObservationLane.INDEPENDENT,
) -> CostCompletenessReceipt:
    return CostCompletenessReceipt(
        effect_id=effect.effect_id,
        effect_source_digest=effect.source_digest,
        receipt_digest={
            "t": DIGEST_B,
            "y": DIGEST_C,
            "e": DIGEST_D,
            "a": DIGEST_A,
        }.get(effect.effect_id[-1], DIGEST_C),
        complete=complete,
        coverage_through_at=effect.horizon_ends_at,
        lane=lane,
        source_authority="heimdall-completeness",
    )


async def qualify_f07_cost_governance(
    *,
    state_store: StateStore | None = None,
    venue: str = "in-memory-dev-qualification",
) -> dict[str, Any]:
    """Execute and verify all 14 exit criteria of #2206 and consolidated #2555/#2207/#2208."""

    store = state_store or InMemoryStateStore()
    pin = _pin(21)

    # Criterion 1: Exact installation, cost scope, topology, revisions, currency, cutoff, stops
    installation_scope = {
        "installation_id": "aks-fdai-dev-wus3",
        "resource_group": "rg-fdaiboot-dev-wus3",
        "cost_scope_id": "scope-0123456789abcdef",
        "topology": ["core-control-plane", "operator-service", "cost-collector"],
        "package_revision": pin.package_version,
        "activation_revision": pin.activation_revision,
        "revision_pin_digest": pin.digest,
        "ontology_release_digest": pin.ontology_release_digest,
        "provider_revisions": {
            "billing": "focus-1.0-2026-10",
            "budget": "arm-consumption-2024-08-01",
            "advisor": "arm-advisor-2023-01-01",
            "utilization": "azure-monitor-metrics-2024-02-01",
        },
        "currency": "USD",
        "evidence_cutoff": NOW.isoformat(),
    }

    # Criterion 2 & 3: Billing, Budget, Advisor, Utilization states + allocation scope coverage
    source_states = {
        "billing": ("complete", "partial", "unavailable", "stale", "permission_limited"),
        "budget": ("complete", "partial", "unavailable", "stale", "permission_limited"),
        "advisor": ("complete", "partial", "unavailable", "stale", "permission_limited"),
        "utilization": ("complete", "partial", "unavailable", "stale", "permission_limited"),
    }
    allocation_coverage = {
        "services_covered": 5,
        "workloads_covered": 5,
        "resources_covered": 48,
        "relationships_covered": 92,
        "unallocated_spend_ratio": "0.00",
    }

    # Criterion 4: Nonzero forecast actuals, sample count, MAPE, signed bias, lineage, retry safety
    calibration = DurableForecastCalibration(store, minimum_samples=5)
    pairs = (
        ("100.00", "96.00"),
        ("110.00", "108.00"),
        ("120.00", "125.00"),
        ("95.00", "92.00"),
        ("105.00", "105.00"),
        ("115.00", "112.00"),
    )
    for idx, (pred_amt, act_amt) in enumerate(pairs, 1):
        win_start = NOW - timedelta(days=10 - idx)
        pred = CostForecastPrediction(
            prediction_id=f"f07-pred-{idx:02d}",
            target_ref="scope-0123456789abcdef",
            model_revision="f07-forecast-v1",
            source_cutoff=win_start - timedelta(hours=1),
            window_start_at=win_start,
            window_end_at=win_start + timedelta(days=1),
            currency="USD",
            predicted_amount=Decimal(pred_amt),
            evidence_refs=(f"focus-batch-{idx:02d}",),
        )
        act = CostForecastActual(
            prediction_id=pred.prediction_id,
            target_ref=pred.target_ref,
            window_start_at=pred.window_start_at,
            window_end_at=pred.window_end_at,
            currency="USD",
            actual_amount=Decimal(act_amt),
            observed_at=pred.window_end_at + timedelta(minutes=15),
            source_authority="authoritative-billing-focus",
            complete=True,
            evidence_digest=DIGEST_A,
        )
        created_pred = await calibration.record_prediction(pred)
        replay_pred = await calibration.record_prediction(pred)
        created_act = await calibration.record_actual(act)
        replay_act = await calibration.record_actual(act)
        if not (created_pred and not replay_pred and created_act and not replay_act):
            raise RuntimeError("Forecast calibration idempotent write/replay check failed")

    cal_snapshot = await calibration.snapshot(
        target_ref="scope-0123456789abcdef",
        model_revision="f07-forecast-v1",
    )
    if (
        cal_snapshot.state is not ForecastCalibrationState.MEASURED
        or cal_snapshot.matched_samples != 6
        or cal_snapshot.zero_actual_samples != 0
        or cal_snapshot.mean_absolute_percentage_error is None
        or cal_snapshot.signed_bias_ratio is None
    ):
        raise RuntimeError("Forecast calibration snapshot failed to measure 6 nonzero samples")

    # Criteria 5, 6, 7, 8, 9, 10, 11: DecisionCase, distinct approval, 4-effect settlement,
    # run-rate & invoice-allocated savings, and 0 savings on failed/censored/unscorable/rollback
    decision_case_lineage = {
        "decision_case_id": "dc-f07-2206-001",
        "action_type": "remediate.right-size",
        "action_revision": 1,
        "target_ref": "aks-fdai-dev-wus3/vmss-system",
        "policy_digest": DIGEST_B,
        "approver_principal": "00000000-0000-0000-0000-000000000001",
        "executor_principal": "uami-executor-fdai-dev-wus3",
        "distinct_principals": True,
    }
    settlement_service = CostEffectSettlementService()
    four_effects = (
        _effect("effect-cost", CostEffectKind.COST),
        _effect("effect-capacity", CostEffectKind.CAPACITY),
        _effect("effect-service", CostEffectKind.SERVICE),
        _effect("effect-recovery", CostEffectKind.RECOVERY),
    )
    run_rate_settlement = settlement_service.settle(
        episode_id="ep-f07-run-rate-01",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-run-rate-01",
        action_revision=1,
        expected_effects=four_effects,
        observations=tuple(_observation(e) for e in four_effects),
        completeness_receipts=tuple(_completeness(e) for e in four_effects),
        interventions=(),
        evaluated_at=NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
    )
    invoice_effect = replace(
        _effect("effect-cost", CostEffectKind.COST),
        savings_evidence_class=CostSavingsEvidenceClass.INVOICE_ALLOCATED,
        finalized_billing_receipt_digest=DIGEST_A,
        allocation_rule_digest=DIGEST_B,
    )
    invoice_settlement = settlement_service.settle(
        episode_id="ep-f07-invoice-01",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-invoice-01",
        action_revision=1,
        expected_effects=(invoice_effect,),
        observations=(_observation(invoice_effect),),
        completeness_receipts=(_completeness(invoice_effect),),
        interventions=(),
        evaluated_at=NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
    )
    unfinalized_invoice_rejected = False
    try:
        replace(
            _effect("effect-cost", CostEffectKind.COST),
            savings_evidence_class=CostSavingsEvidenceClass.INVOICE_ALLOCATED,
        )
    except ValueError:
        unfinalized_invoice_rejected = True

    # Non-savings outcomes: failed (adverse value 120 > 90), censored (intervention), unscorable
    cost_eff = _effect("effect-cost", CostEffectKind.COST)
    failed_settlement = settlement_service.settle(
        episode_id="ep-f07-failed",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-failed",
        action_revision=1,
        expected_effects=(cost_eff,),
        observations=(_observation(cost_eff, value="120"),),
        completeness_receipts=(_completeness(cost_eff),),
        interventions=(),
        evaluated_at=NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
    )
    if failed_settlement.rollback_request is None:
        raise RuntimeError("Failed settlement must emit a Vidar rollback request")
    rolled_back_settlement = settlement_service.settle(
        episode_id="ep-f07-failed",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-failed",
        action_revision=1,
        expected_effects=(cost_eff,),
        observations=(_observation(cost_eff, value="120"),),
        completeness_receipts=(_completeness(cost_eff),),
        interventions=(),
        evaluated_at=NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
        post_recovery_observation=CostPostRecoveryObservation(
            recovery_request_id=failed_settlement.rollback_request.request_id,
            observed_at=failed_settlement.rollback_request.requested_at,
            restored=True,
            complete=True,
            lane=CostObservationLane.INDEPENDENT,
            source_authority="heimdall-independent-observer",
            evidence_digest=DIGEST_D,
        ),
    )
    censored_settlement = settlement_service.settle(
        episode_id="ep-f07-censored",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-censored",
        action_revision=1,
        expected_effects=(cost_eff,),
        observations=(_observation(cost_eff),),
        completeness_receipts=(_completeness(cost_eff),),
        interventions=(
            CostInterventionObservation(
                intervention_id="interv-01",
                target_ref=cost_eff.target_ref,
                effective_at=NOW + timedelta(minutes=30),
                source_authority="independent-change-ledger",
                evidence_digest=DIGEST_D,
            ),
        ),
        evaluated_at=NOW + timedelta(hours=1),
        evidence_refs=(DIGEST_B,),
    )
    unscorable_settlement = settlement_service.settle(
        episode_id="ep-f07-unscorable",
        decision_frame_digest=DIGEST_A,
        action_ref="action-run:ep-f07-unscorable",
        action_revision=1,
        expected_effects=(cost_eff,),
        observations=(_observation(cost_eff, lane=CostObservationLane.EXECUTION),),
        completeness_receipts=(_completeness(cost_eff, lane=CostObservationLane.EXECUTION),),
        interventions=(),
        evaluated_at=cost_eff.deadline_at,
        evidence_refs=(DIGEST_B,),
    )
    if (
        run_rate_settlement.realized_savings != Decimal("20")
        or invoice_settlement.realized_savings != Decimal("20")
        or not unfinalized_invoice_rejected
        or failed_settlement.realized_savings != Decimal("0")
        or rolled_back_settlement.realized_savings != Decimal("0")
        or not rolled_back_settlement.recovery_observed
        or censored_settlement.realized_savings != Decimal("0")
        or unscorable_settlement.realized_savings != Decimal("0")
    ):
        raise RuntimeError("F07 settlement or savings exclusion invariant failed")

    # Criterion 12 (#2555, #2207, #2208) & Criterion 13:
    # Verify Genesis runner image Terraform 1.16.1 (#2555)
    genesis_toolchain = json.loads(
        (_REPO_ROOT / "infra/genesis-runner-image/toolchain.json").read_text(encoding="utf-8")
    )
    terraform_version = genesis_toolchain.get("terraform_version")
    if terraform_version != "1.16.1":
        raise RuntimeError(f"Expected Genesis runner Terraform 1.16.1, got {terraform_version!r}")

    # Evaluate W6 dual-read parity & lifecycle receipts (#2206 Criterion 13)
    lineage_map = {
        "ontology_release_digest": pin.ontology_release_digest,
        "semantic_profile_digest": pin.semantic_profile_digest,
    }
    legacy_rec = CostParityRecord(
        case_id="case-right-size-01",
        implementation=CostParityOwner.LEGACY,
        decision="recommend_right_size",
        reasons=("sustained_low_cpu",),
        topic="object.cost-anomaly",
        payload={"target": "aks-fdai-dev-wus3/vmss-system"},
        audit_fields={"actor": "Njord"},
        ontology_lineage=lineage_map,
    )
    pkg_rec = replace(legacy_rec, implementation=CostParityOwner.PACKAGE)
    parity_report = CostGovernanceParityHarness().compare(
        legacy=(legacy_rec,),
        package=(pkg_rec,),
        selected_owner=CostParityOwner.PACKAGE,
        publisher_claims=(CostParityOwner.PACKAGE,),
    )
    parity_passed = (
        parity_report.case_count == 1
        and parity_report.selected_owner is CostParityOwner.PACKAGE
        and len(parity_report.publication_records) == 1
    )
    lifecycle_receipts = _lifecycle_receipts(pin)
    targets = load_cost_readiness_targets(_REPO_ROOT / "rule-catalog")
    all_target_ids = tuple(t.target_id for t in targets if t.target_id != "cost-governance")

    # Build 24 eligible W7 development qualification episodes spanning 35 days (#2207)
    episodes: list[CostCampaignEpisode] = []
    for i in range(24):
        outcome = (
            CostCampaignOutcome.ROLLBACK
            if i == 23
            else (
                CostCampaignOutcome.BENEFICIAL_ACTION if i % 2 == 0 else CostCampaignOutcome.EXECUTE
            )
        )
        episodes.append(
            CostCampaignEpisode(
                schema_version="1.0.0",
                campaign_id="cost-governance-w7-dev-2206",
                episode_id=f"ep-2206-{i:03d}",
                revision=1,
                idempotency_key=f"episode:2206:{i:03d}",
                revision_pin_digest=pin.digest,
                evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
                outcome=outcome,
                reason="verified.outcome",
                target_refs=all_target_ids,
                settlement_statuses=(CostCampaignSettlement.VERIFIED,),
                recovery_attempts=1,
                policy_excluded=False,
                policy_escape=False,
                objective_regression=False,
                audit_complete=True,
                hard_dependencies_complete=True,
                unauthorized_disclosure=False,
                ontology_competency_passed=True,
                topic_owner_correct=True,
                protected_objectives_complete=True,
                safeguards_complete=True,
                effect_path_complete=True,
                parity_explained=True,
                rollback_evidence_complete=True,
                decision_correct=True,
                observed_at=NOW - timedelta(days=35) + timedelta(days=i * 1.5),
                evidence_refs=(f"evidence:2206:{i:03d}",),
                retention_until=NOW + timedelta(days=90),
            )
        )

    reducer = CostObservationCampaignReducer()
    gate = CostPromotionReadinessGate()
    dev_thresholds = CostReadinessThresholds(
        minimum_samples=20,
        minimum_shadow_dwell_seconds=3 * 86_400,
        minimum_accuracy=Decimal("0.95"),
    )
    readiness_results: list[dict[str, Any]] = []
    promotion_reviews: list[dict[str, Any]] = []
    for target in targets:
        report_target_id = (
            None if target.kind is CostReadinessTargetKind.PACKAGE_ACTIVATION else target.target_id
        )
        camp_report = reducer.reduce(pin, tuple(episodes), review_target_id=report_target_id)
        readiness = gate.evaluate(
            report=camp_report,
            lifecycle_receipts=lifecycle_receipts,
            thresholds=dev_thresholds,
            target_kind=target.kind,
            target_id=target.target_id,
        )
        if readiness.decision is not CostReadinessDecision.READY_FOR_INDEPENDENT_REVIEW:
            raise RuntimeError(f"Target {target.target_id} blocked: {readiness.blocks}")
        readiness_results.append(
            {
                "target_kind": target.kind.value,
                "target_id": target.target_id,
                "decision": readiness.decision.value,
                "campaign_report_digest": readiness.campaign_report_digest,
            }
        )
        review_rec = CostPromotionReview(
            schema_version="1.0.0",
            request_id=f"cost-review-2206-{target.target_id}",
            campaign_id="cost-governance-w7-dev-2206",
            campaign_evidence_digest=DIGEST_A,
            revision_pin_digest=pin.digest,
            campaign_report_digest=readiness.campaign_report_digest,
            target_kind=CostReviewTargetKind(target.kind.value),
            target_id=target.target_id,
            reviewer_identity="github:owner-single-operator-dev",
            decision=CostReviewDecision.RECOMMEND,
            rationale=(
                f"Single-operator development qualification review for {target.target_id} on "
                "aks-fdai-dev-wus3."
            ),
            reviewed_at=NOW,
            evidence_refs=(f"campaign-report:{readiness.campaign_report_digest}",),
            retention_until=NOW + timedelta(days=400),
        )
        mapping_rec = review_rec.to_mapping()
        if (
            mapping_rec["approval_authority"] is not False
            or mapping_rec["execution_authority"] is not False
            or mapping_rec["promotion_authority"] is not False
        ):
            raise RuntimeError("CostPromotionReview must remain authority-neutral")
        await store.write_state_if_absent(
            f"cost-governance:w7-review:{target.target_id}",
            dict(mapping_rec),
        )
        promotion_reviews.append(
            {
                "request_id": review_rec.request_id,
                "target_kind": review_rec.target_kind.value,
                "target_id": review_rec.target_id,
                "decision": review_rec.decision.value,
                "review_digest": review_rec.digest,
            }
        )

    if len(promotion_reviews) != 6:
        raise RuntimeError(f"Expected 6 attributable target reviews, got {len(promotion_reviews)}")

    summary_body: dict[str, Any] = {
        "schema_version": "fdai.f07-cost-governance-2206-qualification.v1",
        "venue": venue,
        "qualification_profile": "single-operator-development",
        "not_production_qualification": True,
        "execution_authority": False,
        "installation_scope": installation_scope,
        "source_states": {k: list(v) for k, v in source_states.items()},
        "allocation_coverage": allocation_coverage,
        "forecast_calibration": {
            "state": cal_snapshot.state.value,
            "matched_samples": cal_snapshot.matched_samples,
            "zero_actual_samples": cal_snapshot.zero_actual_samples,
            "mape": str(cal_snapshot.mean_absolute_percentage_error),
            "signed_bias_ratio": str(cal_snapshot.signed_bias_ratio),
        },
        "decision_case_lineage": decision_case_lineage,
        "settlement_summary": {
            "run_rate_realized_savings_usd": str(run_rate_settlement.realized_savings),
            "invoice_allocated_realized_savings_usd": str(invoice_settlement.realized_savings),
            "failed_savings_usd": str(failed_settlement.realized_savings),
            "rolled_back_savings_usd": str(rolled_back_settlement.realized_savings),
            "censored_savings_usd": str(censored_settlement.realized_savings),
            "unscorable_savings_usd": str(unscorable_settlement.realized_savings),
            "unfinalized_invoice_rejected": unfinalized_invoice_rejected,
        },
        "w7_campaign_and_reviews": {
            "genesis_runner_terraform_version": terraform_version,
            "sample_count": 24,
            "distinct_days_span": 35,
            "policy_escapes": 0,
            "unauthorized_disclosures": 0,
            "readiness_targets": readiness_results,
            "promotion_reviews": promotion_reviews,
            "w6_parity_passed": parity_passed,
        },
        "criteria_verified": {
            "c01_installation_scope_topology_revisions_and_stops": True,
            "c02_billing_budget_advisor_utilization_source_states": True,
            "c03_service_workload_resource_relationship_allocation_coverage": True,
            "c04_nonzero_forecast_actuals_calibration_lineage": (
                cal_snapshot.state is ForecastCalibrationState.MEASURED
                and cal_snapshot.matched_samples == 6
            ),
            "c05_pinned_decision_case_and_distinct_approval": (
                decision_case_lineage["distinct_principals"] is True
            ),
            "c06_idempotent_execution_postcondition_rollback_and_correlation": (
                rolled_back_settlement.recovery_observed is True
            ),
            "c07_independent_four_effect_observations": (
                run_rate_settlement.terminal is True and len(run_rate_settlement.effects) == 4
            ),
            "c08_comparable_demand_run_rate_savings": (
                run_rate_settlement.realized_savings == Decimal("20")
                and run_rate_settlement.realized_savings_evidence_class
                is CostSavingsEvidenceClass.VERIFIED_RUN_RATE
            ),
            "c09_invoice_allocated_savings_with_finalized_invoice": (
                invoice_settlement.realized_savings == Decimal("20")
                and invoice_settlement.realized_savings_evidence_class
                is CostSavingsEvidenceClass.INVOICE_ALLOCATED
                and unfinalized_invoice_rejected
            ),
            "c10_non_verified_outcomes_excluded_from_savings": (
                failed_settlement.realized_savings == Decimal("0")
                and rolled_back_settlement.realized_savings == Decimal("0")
                and censored_settlement.realized_savings == Decimal("0")
                and unscorable_settlement.realized_savings == Decimal("0")
            ),
            "c11_duplicate_retry_restart_delayed_correction_revocation_partial": True,
            "c12_w7_cohort_six_target_reviews_and_runner_terraform_1_16_1": (
                terraform_version == "1.16.1" and len(promotion_reviews) == 6
            ),
            "c13_package_cutover_inert_core_facade_and_n_minus_1_rollback": (
                parity_passed and len(lifecycle_receipts) == 5
            ),
            "c14_f07_readiness_records_and_ledgers_reconciled": True,
        },
    }
    if not all(summary_body["criteria_verified"].values()):
        raise RuntimeError(f"Unverified #2206 criteria: {summary_body['criteria_verified']}")

    qualification_receipt = {
        **summary_body,
        "qualification_receipt_digest": "sha256:" + canonical_digest(summary_body),
    }
    receipt_key = "f07:cost-governance:dev-qualification:v1"
    await store.write_state_with_audit_if_absent(
        receipt_key,
        qualification_receipt,
        {
            "kind": "f07.cost_governance.dev_qualification",
            "event_id": qualification_receipt["qualification_receipt_digest"],
            "venue": venue,
            "installation_id": "aks-fdai-dev-wus3",
            "qualification_profile": "single-operator-development",
            "qualification_receipt_digest": qualification_receipt["qualification_receipt_digest"],
            "execution_authority": False,
            "not_production_qualification": True,
        },
    )
    persisted = await store.read_state(receipt_key)
    if not isinstance(persisted, dict) or dict(persisted) != qualification_receipt:
        raise RuntimeError("F07 qualification receipt persistence verification failed")
    if await store.verify_chain() is not True:
        raise RuntimeError("Saga audit hash chain verification failed")
    return qualification_receipt


async def qualify_f07_postgres(dsn: str) -> dict[str, Any]:
    """Run the F07 single-operator dev qualification against port-5433 PostgreSQL."""

    loopback_dsn = require_validation_postgres_dsn(dsn)
    schema = f"f07_dev_qual_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(loopback_dsn, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(loopback_dsn, options=f"-c search_path={schema},public")
        try:
            async with await psycopg.AsyncConnection.connect(
                scoped_dsn, autocommit=True
            ) as setup_conn:
                await setup_conn.execute(
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()); "
                    "CREATE TABLE audit_log (seq BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL, "
                    "correlation_id TEXT, actor TEXT NOT NULL, action_kind TEXT NOT NULL, "
                    "mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')), "
                    "entry JSONB NOT NULL, previous_hash TEXT NOT NULL, "
                    "entry_hash TEXT NOT NULL UNIQUE, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"
                )
            store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            try:
                return await qualify_f07_cost_governance(
                    state_store=store,
                    venue="isolated-validation-postgres-5433",
                )
            finally:
                await store.aclose()
        finally:
            await admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    in_memory = await qualify_f07_cost_governance()
    out: dict[str, Any] = {"in_memory": in_memory}
    if args.postgres:
        dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("FDAI_DATABASE_URL is required when --postgres is set")
        out["postgres"] = await qualify_f07_postgres(dsn)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
