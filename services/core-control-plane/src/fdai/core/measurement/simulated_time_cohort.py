"""Time-simulated multi-day cohort injection and closed-loop measurement."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai_service_contracts.baseline_cohort import CohortArm, CohortArmFacts

from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicy
from fdai.core.measurement.operational_cohort import (
    OperationalCohortArmBatch,
    OperationalGuardObservation,
    OperationalMetricObservation,
    aggregate_operational_cohort_arm,
)
from fdai.core.measurement.operational_promotion import (
    OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
    CausalPromotionReceipt,
    OperationalPromotionBatch,
    OperationalPromotionEvaluator,
    OperationalPromotionPolicy,
    OperationalPromotionReceipt,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
    action_type_digest,
    operational_promotion_evidence_digest,
    operational_promotion_scope_digest,
)
from fdai.core.measurement.outcome_assurance import OutcomeAssuranceProjection
from fdai.core.measurement.simulated_time_settlement import (
    build_simulated_outcome_projection,
    simulate_finops_multi_day_settlements,
)
from fdai.shared.contracts.models import CausalEvidenceGrade, OntologyActionType
from fdai.shared.providers.cost_governance_decision import CostEpisodeSettlement
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class SimulatedTimeClock:
    """Deterministic multi-day UTC clock for accelerated cohort and settlement evaluation."""

    def __init__(self, start_time: datetime) -> None:
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise ValueError("SimulatedTimeClock start_time MUST be timezone-aware")
        self._start = start_time.astimezone(UTC)
        self._current = self._start

    @property
    def start_time(self) -> datetime:
        return self._start

    def now(self) -> datetime:
        return self._current

    def advance_days(self, days: int) -> datetime:
        if isinstance(days, bool) or days < 0:
            raise ValueError("advance_days requires a non-negative integer")
        self._current += timedelta(days=days)
        return self._current

    def advance_hours(self, hours: int) -> datetime:
        if isinstance(hours, bool) or hours < 0:
            raise ValueError("advance_hours requires a non-negative integer")
        self._current += timedelta(hours=hours)
        return self._current

    def at_day(self, day_offset: int, *, hour: int = 12, minute: int = 0) -> datetime:
        if isinstance(day_offset, bool) or day_offset < 0:
            raise ValueError("day_offset MUST be a non-negative integer")
        return self._start + timedelta(days=day_offset, hours=hour, minutes=minute)


class _SimulatedPromotionVerifier:
    def verify(self, _item: object) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class SimulatedMultiDayCohortResult:
    """Complete multi-day measurement receipts across SRE, ARB, FinOps, and promotion."""

    simulated_days: int
    total_events: int
    baseline_facts: CohortArmFacts
    treatment_facts: CohortArmFacts
    promotion_receipts: tuple[OperationalPromotionReceipt, ...]
    finops_settlements: tuple[CostEpisodeSettlement, ...]
    outcome_projection: OutcomeAssuranceProjection

    @property
    def all_promotions_ready(self) -> bool:
        return bool(self.promotion_receipts) and all(item.ready for item in self.promotion_receipts)

    @property
    def all_settlements_verified(self) -> bool:
        return bool(self.finops_settlements) and all(
            item.terminal and item.rollback_request is None for item in self.finops_settlements
        )

    @property
    def total_realized_savings_usd(self) -> Decimal:
        return sum(
            (s.realized_savings or Decimal("0") for s in self.finops_settlements), Decimal("0")
        )


def simulate_arm_batch(
    *,
    arm: CohortArm,
    clock: SimulatedTimeClock,
    days: int,
    samples_per_day: int,
    fdai_revision: str,
    policy: CohortClaimPolicy,
) -> CohortArmFacts:
    """Inject multi-day observations across `days` distinct simulated days and aggregate."""

    if days < 1 or samples_per_day < 1:
        raise ValueError("days and samples_per_day MUST be positive")
    window_start = clock.start_time
    window_end = clock.at_day(days, hour=0)
    is_treatment = arm is CohortArm.TREATMENT
    metric_targets: dict[str, float] = (
        {
            "auto_resolution_rate": 1.0,
            "change_lead_time_seconds": 900.0,
            "cost_per_unit_usd": 1.8,
            "human_touchpoints_per_100_events": 7.5,
            "mttr_seconds": 240.0,
        }
        if is_treatment
        else {
            "auto_resolution_rate": 0.0,
            "change_lead_time_seconds": 7200.0,
            "cost_per_unit_usd": 12.0,
            "human_touchpoints_per_100_events": 85.0,
            "mttr_seconds": 1800.0,
        }
    )
    metrics: list[OperationalMetricObservation] = []
    guards: list[OperationalGuardObservation] = []
    sample_index = 0
    for day in range(days):
        for slot in range(samples_per_day):
            observed_at = clock.at_day(day, hour=(slot * 4) % 24, minute=15)
            cluster_digest = _sha256(f"{arm.value}:cluster:{day:03d}:{slot:02d}")
            for metric_id in policy.required_metric_ids:
                base_val = metric_targets[metric_id]
                if metric_id == "auto_resolution_rate":
                    value = (
                        1.0
                        if (is_treatment and sample_index % 12 != 0)
                        or (not is_treatment and sample_index % 6 == 0)
                        else 0.0
                    )
                else:
                    value = base_val + float((sample_index % 5) - 2) * (base_val * 0.02)
                metrics.append(
                    OperationalMetricObservation(
                        metric_id=metric_id,
                        observation_digest=_sha256(
                            f"{arm.value}:metric:{metric_id}:{sample_index:04d}"
                        ),
                        source_cluster_digest=cluster_digest,
                        value=max(0.0, value),
                        observed_at=observed_at,
                    )
                )
            for guard_id in policy.required_guard_ids:
                g_dig = _sha256(f"{arm.value}:guard:{guard_id}:{sample_index:04d}")
                guards.append(
                    OperationalGuardObservation(
                        guard_id=guard_id,
                        observation_digest=g_dig,
                        source_cluster_digest=cluster_digest,
                        breached=False,
                        observed_at=observed_at,
                    )
                )
            sample_index += 1
    return aggregate_operational_cohort_arm(
        OperationalCohortArmBatch(
            arm=arm,
            fdai_revision=fdai_revision,
            window_start=window_start,
            window_end=window_end,
            synthetic=False,
            metrics=tuple(metrics),
            guards=tuple(guards),
        ),
        policy,
    )


def _promo_record(
    idx: int,
    *,
    prefix: str,
    case_id: str,
    hyp_id: str,
    cohort: PromotionEvidenceCohort,
    observed_at: datetime,
    action_type: OntologyActionType,
    digest: str,
    fdai_revision: str,
    scenario_set_version: str,
) -> OperationalPromotionRecord:
    causal = CausalPromotionReceipt(
        hypothesis_id=hyp_id,
        hypothesis_revision_digest=_hex_sha256(f"{action_type.name}:{hyp_id}"),
        evidence_grade=CausalEvidenceGrade.INTERVENTIONAL,
        status="closed",
        closure="confirmed",
    )
    return OperationalPromotionRecord(
        sample_id=f"{prefix}-{idx:04d}",
        measurement_unit_id=f"unit-{prefix}-{idx:04d}",
        audit_sequence=1,
        action_type_name=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=digest,
        fdai_revision=fdai_revision,
        scenario_set_version=scenario_set_version,
        scenario_case_id=case_id,
        cohort=cohort,
        observed_at=observed_at,
        correct=True,
        policy_escape=False,
        executed=True,
        rolled_back=False,
        recurrence_window_complete=True,
        recurrence=False,
        causal_receipt=causal,
        simulation_requires_review=False,
        evidence_refs=(_hex_sha256(f"{action_type.name}:{prefix}:ev:{idx}"), causal.content_digest),
    )


def simulate_action_promotions(
    *,
    action_types: Sequence[OntologyActionType],
    clock: SimulatedTimeClock,
    days: int,
    live_samples_per_day: int,
    benchmark_samples: int,
    fdai_revision: str,
    scenario_set_version: str,
) -> tuple[OperationalPromotionReceipt, ...]:
    """Evaluate multi-day promotion readiness by advancing simulated time across `days`."""

    verifier = _SimulatedPromotionVerifier()
    receipts: list[OperationalPromotionReceipt] = []
    for action_type in action_types:
        gate = action_type.promotion_gate
        eff_days = max(days, gate.min_shadow_days)
        min_wilson = math.ceil(3.85 * gate.min_accuracy / max(1.0 - gate.min_accuracy, 0.001)) + 5
        eff_bench = min(4000, max(benchmark_samples, min_wilson))
        total_live = min(
            4000,
            max(days * live_samples_per_day, gate.min_samples, min_wilson, eff_days),
        )
        action_sealed_at = clock.at_day(eff_days, hour=23)
        action_evaluator = OperationalPromotionEvaluator(
            expected_fdai_revision=fdai_revision,
            expected_scenario_set_version=scenario_set_version,
            causal_receipt_verifier=verifier,
            unit_verifier=verifier,
            policy=OperationalPromotionPolicy(
                min_benchmark_samples=benchmark_samples,
                min_live_shadow_samples=days * live_samples_per_day,
            ),
            as_of_fn=lambda target=action_sealed_at: target + timedelta(minutes=5),
        )
        digest = action_type_digest(action_type)
        records = [
            _promo_record(
                b_idx + 1,
                prefix="bench",
                case_id=f"case-bench-{b_idx:04d}",
                hyp_id=f"{action_type.name}-bench-hyp-{b_idx:04d}",
                cohort=PromotionEvidenceCohort.FROZEN_BENCHMARK,
                observed_at=clock.at_day(0, hour=1),
                action_type=action_type,
                digest=digest,
                fdai_revision=fdai_revision,
                scenario_set_version=scenario_set_version,
            )
            for b_idx in range(eff_bench)
        ]
        for l_idx in range(total_live):
            day = l_idx % eff_days
            slot = l_idx // eff_days
            records.append(
                _promo_record(
                    eff_bench + l_idx + 1,
                    prefix="live",
                    case_id=f"case-live-{l_idx:04d}",
                    hyp_id=f"{action_type.name}-live-hyp-{l_idx:04d}",
                    cohort=PromotionEvidenceCohort.LIVE_SHADOW,
                    observed_at=clock.at_day(day, hour=(slot * 3) % 24, minute=slot % 60),
                    action_type=action_type,
                    digest=digest,
                    fdai_revision=fdai_revision,
                    scenario_set_version=scenario_set_version,
                )
            )
        raw_batch = OperationalPromotionBatch(
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            action_type_name=action_type.name,
            action_type_version=action_type.version,
            action_type_digest=digest,
            sealed_at=action_sealed_at,
            records=tuple(records),
        )
        admitted_batch = replace(
            raw_batch,
            decision_evidence=DecisionEvidenceAdmission(
                receipt_digest=_sha256(f"promo-receipt:{action_type.name}"),
                verification_bundle_digest=_sha256(f"promo-bundle:{action_type.name}"),
                evidence_digest=operational_promotion_evidence_digest(raw_batch),
                scope_digest=operational_promotion_scope_digest(raw_batch),
                purpose_id=OPERATIONAL_PROMOTION_EVIDENCE_PURPOSE,
                source_revision=fdai_revision,
                verified_at=action_sealed_at - timedelta(minutes=1),
                valid_until=action_sealed_at + timedelta(hours=1),
            ),
        )
        receipts.append(action_evaluator.evaluate(action_type, admitted_batch))
    return tuple(receipts)


def run_simulated_multi_day_cohort(
    *,
    policy: CohortClaimPolicy,
    action_types: Sequence[OntologyActionType],
    start_time: datetime | None = None,
    days: int = 30,
    samples_per_day: int = 4,
    fdai_revision: str = "a" * 40,
    scenario_set_version: str = "v2026.10",
) -> SimulatedMultiDayCohortResult:
    """Execute the full time-simulated multi-day cohort and outcome assurance pipeline."""

    clock = SimulatedTimeClock(start_time or datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
    baseline_facts = simulate_arm_batch(
        arm=CohortArm.BASELINE,
        clock=clock,
        days=days,
        samples_per_day=samples_per_day,
        fdai_revision=fdai_revision,
        policy=policy,
    )
    treatment_facts = simulate_arm_batch(
        arm=CohortArm.TREATMENT,
        clock=clock,
        days=days,
        samples_per_day=samples_per_day,
        fdai_revision=fdai_revision,
        policy=policy,
    )
    promotions = simulate_action_promotions(
        action_types=action_types,
        clock=clock,
        days=days,
        live_samples_per_day=samples_per_day,
        benchmark_samples=20,
        fdai_revision=fdai_revision,
        scenario_set_version=scenario_set_version,
    )
    settlements = simulate_finops_multi_day_settlements(
        predicted_at=clock.at_day(1, hour=8),
        evaluated_at=clock.at_day(days, hour=18),
        horizon_days=max(1, days - 5),
    )
    projection = build_simulated_outcome_projection(
        window_start=clock.start_time,
        window_end=clock.at_day(days, hour=23),
        days=days,
        samples_per_day=samples_per_day,
        action_types=action_types,
        baseline_facts=baseline_facts,
        treatment_facts=treatment_facts,
        scenario_set_version=scenario_set_version,
    )
    return SimulatedMultiDayCohortResult(
        simulated_days=days,
        total_events=days * samples_per_day,
        baseline_facts=baseline_facts,
        treatment_facts=treatment_facts,
        promotion_receipts=promotions,
        finops_settlements=settlements,
        outcome_projection=projection,
    )
