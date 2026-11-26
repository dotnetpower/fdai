"""Predeclared SLO-gated operational-learning qualification and separate effect reporting."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.assurance_twin.feedback_rebuild import latest_feedback_revisions
from fdai.shared.contracts.execution_outcomes import (
    ExecutionLifecycleDisposition,
    execution_lifecycle_disposition,
)
from fdai.shared.contracts.models import EffectPredictionSnapshot, ResponseOutcome

_HEX64 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_WILSON_Z_95 = 1.959963984540054


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} MUST be timezone-aware")
    return value


def _require_non_empty(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} MUST be non-empty")
    return stripped


def _wilson_95(successes: int, denominator: int) -> tuple[float | None, float | None]:
    if denominator <= 0:
        return None, None
    p = successes / denominator
    z2 = _WILSON_Z_95 * _WILSON_Z_95
    denom = 1.0 + z2 / denominator
    centre = (p + z2 / (2.0 * denominator)) / denom
    variance = (p * (1.0 - p)) / denominator + z2 / (4.0 * denominator * denominator)
    margin = _WILSON_Z_95 * math.sqrt(variance) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


@dataclass(frozen=True, slots=True)
class QualificationVenueSelection:
    """Explicitly authorized installation, target, source revisions, and validation scope."""

    installation_id: str
    venue: str
    target_scope_digest: str
    access_scope_digest: str
    fdai_revision: str
    read_source_revision: str
    graph_source_revision: str
    slo_revision: str
    safety_budget_revision: str
    window_start: datetime
    window_end: datetime
    deadline_seconds: float = 5.0
    authorized_by_operator: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.installation_id, "installation_id")
        venue = _require_non_empty(self.venue, "venue")
        if (
            venue in {"runtime", "production-unscoped", "port:5432"}
            or not self.authorized_by_operator
        ):
            raise PermissionError("qualification venue MUST be explicitly authorized and isolated")
        for label, digest in (
            ("target_scope_digest", self.target_scope_digest),
            ("access_scope_digest", self.access_scope_digest),
            ("graph_source_revision", self.graph_source_revision),
        ):
            if _HEX64.fullmatch(digest) is None:
                raise ValueError(f"{label} MUST be a 64-hex SHA-256 digest")
        for label, rev in (
            ("fdai_revision", self.fdai_revision),
            ("read_source_revision", self.read_source_revision),
            ("slo_revision", self.slo_revision),
            ("safety_budget_revision", self.safety_budget_revision),
        ):
            _require_non_empty(rev, label)
        if _require_aware(self.window_end, "window_end") <= _require_aware(
            self.window_start, "window_start"
        ):
            raise ValueError("validation window_end MUST follow window_start")
        if not math.isfinite(self.deadline_seconds) or not 0.01 <= self.deadline_seconds <= 300.0:
            raise ValueError("validation deadline_seconds is out of bounds")

    @property
    def scope_manifest_digest(self) -> str:
        payload = asdict(self)
        payload["window_start"] = self.window_start.astimezone(UTC).isoformat()
        payload["window_end"] = self.window_end.astimezone(UTC).isoformat()
        return content_digest(payload)


@dataclass(frozen=True, slots=True)
class PredeclaredLearningEvaluationGates:
    """Predeclared evaluation gates bound to existing safety budgets and SLOs."""

    slo_revision: str
    safety_budget_revision: str
    min_independent_episodes_per_arm: int = 3
    min_time_separation: timedelta = timedelta(minutes=5)
    observation_window: timedelta = timedelta(hours=1)
    recurrence_window: timedelta = timedelta(hours=24)
    min_recovery_rate: float = 0.80
    max_recurrence_rate: float = 0.10
    max_rollback_rate: float = 0.05
    max_side_effect_count: int = 0
    max_policy_escape_count: int = 0
    max_mean_absolute_error: float = 15.0
    max_brier_score: float = 0.15
    min_interval_coverage: float = 0.80

    def __post_init__(self) -> None:
        _require_non_empty(self.slo_revision, "slo_revision")
        _require_non_empty(self.safety_budget_revision, "safety_budget_revision")
        if self.min_independent_episodes_per_arm < 1:
            raise ValueError("min_independent_episodes_per_arm MUST be >= 1")
        if min(
            self.min_time_separation, self.observation_window, self.recurrence_window
        ) <= timedelta(0):
            raise ValueError("evaluation windows and separation MUST be positive")
        for rate in (
            self.min_recovery_rate,
            self.max_recurrence_rate,
            self.max_rollback_rate,
            self.max_brier_score,
            self.min_interval_coverage,
        ):
            if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
                raise ValueError("predeclared probability/rate gates MUST be in [0, 1]")
        if self.max_side_effect_count < 0 or self.max_policy_escape_count < 0:
            raise ValueError("zero-budget safety counts MUST be non-negative")
        if not math.isfinite(self.max_mean_absolute_error) or self.max_mean_absolute_error <= 0:
            raise ValueError("max_mean_absolute_error MUST be positive")

    @property
    def gate_plan_digest(self) -> str:
        payload = asdict(self)
        for key in ("min_time_separation", "observation_window", "recurrence_window"):
            payload[key + "_seconds"] = payload.pop(key).total_seconds()
        return content_digest(payload)


@dataclass(frozen=True, slots=True)
class FrozenProvenanceQualification:
    """Qualification summary for frozen predictor/observer provenance and retention."""

    total_latest_outcomes: int
    qualified_interventions_count: int
    unknown_preserved_count: int
    held_provenance_count: int
    qualified_outcome_ids: tuple[str, ...]
    unknown_outcome_ids: tuple[str, ...]
    execution_authority: bool = field(default=False, init=False)
    promotion_authority: bool = field(default=False, init=False)


def qualify_frozen_intervention_provenance(
    outcomes: Sequence[ResponseOutcome],
    *,
    retained_predictions: Mapping[str, EffectPredictionSnapshot],
    model_generation_digests: frozenset[str],
    as_of: datetime,
) -> FrozenProvenanceQualification:
    """Qualify frozen predictor/observer provenance and preserve unknown outcomes."""
    _require_aware(as_of, "as_of")
    latest = latest_feedback_revisions(tuple(outcomes), as_of=as_of)
    qualified_ids: list[str] = []
    unknown_ids: list[str] = []
    held = 0
    for outcome in latest:
        if not outcome.scorable or outcome.observed_value is None:
            unknown_ids.append(str(outcome.outcome_id))
            continue
        snapshot = outcome.prediction_snapshot
        if snapshot is None:
            held += 1
            continue
        retained = retained_predictions.get(snapshot.prediction_id) or retained_predictions.get(
            snapshot.digest
        )
        if (
            retained is None
            or retained.digest != snapshot.digest
            or snapshot.model_digest not in model_generation_digests
            or not outcome.observation_receipt_ref
            or outcome.observation_unit != snapshot.unit
            or outcome.observed_at is None
            or outcome.observed_at <= snapshot.predicted_at
            or outcome.recorded_at < snapshot.predicted_at
            or outcome.execution_mode.value != "enforce"
            or outcome.decision not in {"auto", "hil"}
            or execution_lifecycle_disposition(outcome.execution_outcome)
            is not ExecutionLifecycleDisposition.ACCEPTED
            or outcome.rollback_succeeded is not False
        ):
            held += 1
            continue
        qualified_ids.append(str(outcome.outcome_id))
    return FrozenProvenanceQualification(
        total_latest_outcomes=len(latest),
        qualified_interventions_count=len(qualified_ids),
        unknown_preserved_count=len(unknown_ids),
        held_provenance_count=held,
        qualified_outcome_ids=tuple(qualified_ids),
        unknown_outcome_ids=tuple(unknown_ids),
    )


@dataclass(frozen=True, slots=True)
class FrozenT1ShadowIntakeSummary:
    """Independent frozen evaluation of bounded eligible T1 selection and shadow intake."""

    evaluated_events: int
    baseline_selections_preserved: int
    coherent_qualified_shadow_matches: int
    leased_qualified_shadow_matches: int
    withdrawal_rejections_verified: int
    deadline_and_cancellation_holds_verified: int
    stale_or_expired_holds_verified: int
    execution_authority_granted: bool = False
    promotion_authority_granted: bool = False
    baseline_mutated: bool = False

    def __post_init__(self) -> None:
        if (
            self.execution_authority_granted
            or self.promotion_authority_granted
            or self.baseline_mutated
        ):
            raise ValueError("shadow intake evaluation MUST NOT grant authority or mutate baseline")
        if (
            self.evaluated_events < 1
            or self.baseline_selections_preserved != self.evaluated_events
            or self.coherent_qualified_shadow_matches < 1
            or self.leased_qualified_shadow_matches < 1
            or self.withdrawal_rejections_verified < 1
            or self.deadline_and_cancellation_holds_verified < 1
            or self.stale_or_expired_holds_verified < 1
        ):
            raise ValueError("frozen T1 and shadow intake evaluation coverage is incomplete")


@dataclass(frozen=True, slots=True)
class OperationalLearningEpisode:
    """One baseline or challenger episode observation before retry/replay deduplication."""

    episode_id: str
    arm: Literal["baseline", "challenger"]
    incident_id: str
    independence_key: str
    common_cause_key: str
    idempotency_key: str
    observed_at: datetime
    is_retry_or_replay: bool = False
    execution_mode: Literal["shadow", "enforce"] = "shadow"
    decision: Literal["auto", "hil", "deny", "abstain"] = "abstain"
    recommended: bool = False
    abstained: bool = False
    intervention_completed: bool = False
    outcome_known: bool = True
    recovered: bool | None = None
    recovery_seconds: float | None = None
    recurrence_window_complete: bool = False
    recurred: bool | None = None
    rolled_back: bool = False
    side_effect_escaped: bool = False
    policy_escaped: bool = False
    predicted_recovery_probability: float | None = None
    point_prediction: float | None = None
    interval_lower: float | None = None
    interval_upper: float | None = None
    observed_value: float | None = None
    propensity_overlap_verified: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryMetrics:
    executed_denominator: int
    recovered_count: int
    recovery_rate: float | None
    wilson_95_lower: float | None
    wilson_95_upper: float | None
    mean_recovery_seconds: float | None
    unknown_outcome_count: int


@dataclass(frozen=True, slots=True)
class RecurrenceMetrics:
    completed_window_denominator: int
    recurred_count: int
    recurrence_rate: float | None
    wilson_95_lower: float | None
    wilson_95_upper: float | None
    censored_incomplete_window_count: int


@dataclass(frozen=True, slots=True)
class RollbackAndSideEffectMetrics:
    executed_denominator: int
    rolled_back_count: int
    rollback_rate: float | None
    rollback_wilson_95_upper: float | None
    side_effect_count: int
    side_effect_rate: float | None
    side_effect_wilson_95_upper: float | None
    policy_escape_count: int


@dataclass(frozen=True, slots=True)
class AbstentionAndCoverageMetrics:
    independent_episode_denominator: int
    recommended_count: int
    recommendation_coverage: float | None
    coverage_wilson_95_lower: float | None
    coverage_wilson_95_upper: float | None
    abstained_count: int
    abstention_rate: float | None
    abstention_wilson_95_lower: float | None
    abstention_wilson_95_upper: float | None
    conditional_success_rate: float | None


@dataclass(frozen=True, slots=True)
class PredictionAndCalibrationMetrics:
    scored_scalar_count: int
    mean_absolute_error: float | None
    root_mean_squared_error: float | None
    interval_coverage: float | None
    interval_coverage_wilson_95_lower: float | None
    interval_coverage_wilson_95_upper: float | None
    mean_interval_width: float | None
    calibration_sample_count: int
    brier_score: float | None
    expected_calibration_error: float | None


@dataclass(frozen=True, slots=True)
class SampleCountAndUncertaintySummary:
    raw_observation_count: int
    excluded_retry_or_replay_count: int
    excluded_duplicate_group_count: int
    excluded_time_separation_count: int
    independent_episode_count: int
    unknown_outcome_count: int
    confidence_level: float = 0.95
    interval_method: str = "wilson_score_95"


@dataclass(frozen=True, slots=True)
class ArmOperationalMetrics:
    arm: Literal["baseline", "challenger"]
    recovery: RecoveryMetrics
    recurrence: RecurrenceMetrics
    rollback_and_side_effects: RollbackAndSideEffectMetrics
    abstention_and_coverage: AbstentionAndCoverageMetrics
    prediction_and_calibration: PredictionAndCalibrationMetrics
    sample_counts: SampleCountAndUncertaintySummary


@dataclass(frozen=True, slots=True)
class OperationalLearningEffectReport:
    scope: QualificationVenueSelection
    gates: PredeclaredLearningEvaluationGates
    provenance: FrozenProvenanceQualification
    t1_shadow_intake: FrozenT1ShadowIntakeSummary
    baseline: ArmOperationalMetrics
    challenger: ArmOperationalMetrics
    gates_passed: bool
    gate_failures: tuple[str, ...]
    policy_effect_claimed: bool = False
    execution_authority: bool = field(default=False, init=False)
    promotion_authority: bool = field(default=False, init=False)

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope"]["window_start"] = self.scope.window_start.astimezone(UTC).isoformat()
        payload["scope"]["window_end"] = self.scope.window_end.astimezone(UTC).isoformat()
        for key in ("min_time_separation", "observation_window", "recurrence_window"):
            payload["gates"][key + "_seconds"] = payload["gates"].pop(key).total_seconds()
        payload["scope_manifest_digest"] = self.scope.scope_manifest_digest
        payload["gate_plan_digest"] = self.gates.gate_plan_digest
        return payload


def _evaluate_arm(
    arm: Literal["baseline", "challenger"],
    episodes: Sequence[OperationalLearningEpisode],
    *,
    gates: PredeclaredLearningEvaluationGates,
    seen_incidents: set[str],
    seen_independence: set[str],
    seen_common_cause: set[str],
    seen_idempotency: set[str],
) -> tuple[ArmOperationalMetrics, list[OperationalLearningEpisode]]:
    raw_count = len(episodes)
    retry_excluded = 0
    dup_excluded = 0
    time_excluded = 0
    independent: list[OperationalLearningEpisode] = []
    last_time: datetime | None = None
    for ep in sorted(episodes, key=lambda item: (item.observed_at, item.episode_id)):
        _require_aware(ep.observed_at, "episode.observed_at")
        if ep.is_retry_or_replay:
            retry_excluded += 1
            continue
        if (
            ep.incident_id in seen_incidents
            or ep.independence_key in seen_independence
            or ep.common_cause_key in seen_common_cause
            or ep.idempotency_key in seen_idempotency
        ):
            dup_excluded += 1
            continue
        if last_time is not None and (ep.observed_at - last_time) < gates.min_time_separation:
            time_excluded += 1
            continue
        seen_incidents.add(ep.incident_id)
        seen_independence.add(ep.independence_key)
        seen_common_cause.add(ep.common_cause_key)
        seen_idempotency.add(ep.idempotency_key)
        last_time = ep.observed_at
        independent.append(ep)

    unknown_count = sum(1 for ep in independent if not ep.outcome_known)
    executed_known = [
        ep
        for ep in independent
        if ep.intervention_completed and ep.execution_mode == "enforce" and ep.outcome_known
    ]
    exec_denom = len(executed_known)
    recovered_eps = [ep for ep in executed_known if ep.recovered is True and not ep.rolled_back]
    recovered_count = len(recovered_eps)
    rec_rate = recovered_count / exec_denom if exec_denom else None
    rec_low, rec_high = _wilson_95(recovered_count, exec_denom)
    rec_times = [
        ep.recovery_seconds
        for ep in recovered_eps
        if ep.recovery_seconds is not None and ep.recovery_seconds >= 0
    ]
    mean_rec_sec = math.fsum(rec_times) / len(rec_times) if rec_times else None

    completed_rec_window = [
        ep for ep in executed_known if ep.recurrence_window_complete and ep.recurred is not None
    ]
    censored_rec = sum(1 for ep in executed_known if not ep.recurrence_window_complete)
    rec_win_denom = len(completed_rec_window)
    recurred_count = sum(1 for ep in completed_rec_window if ep.recurred is True)
    recurrence_rate = recurred_count / rec_win_denom if rec_win_denom else None
    recur_low, recur_high = _wilson_95(recurred_count, rec_win_denom)

    rolled_back_count = sum(1 for ep in executed_known if ep.rolled_back)
    rollback_rate = rolled_back_count / exec_denom if exec_denom else None
    _, rb_upper = _wilson_95(rolled_back_count, exec_denom)
    side_effect_count = sum(1 for ep in independent if ep.side_effect_escaped)
    side_effect_rate = side_effect_count / exec_denom if exec_denom else None
    _, se_upper = _wilson_95(side_effect_count, exec_denom)
    policy_escape_count = sum(1 for ep in independent if ep.policy_escaped)

    ind_denom = len(independent)
    recommended_count = sum(1 for ep in independent if ep.recommended)
    abstained_count = sum(1 for ep in independent if ep.abstained)
    cov_rate = recommended_count / ind_denom if ind_denom else None
    cov_low, cov_high = _wilson_95(recommended_count, ind_denom)
    abs_rate = abstained_count / ind_denom if ind_denom else None
    abs_low, abs_high = _wilson_95(abstained_count, ind_denom)
    recommended_executed = [ep for ep in executed_known if ep.recommended]
    cond_success = (
        sum(1 for ep in recommended_executed if ep.recovered is True and not ep.rolled_back)
        / len(recommended_executed)
        if recommended_executed
        else None
    )

    scalar_tuples = [
        (ep.point_prediction, ep.observed_value, ep.interval_lower, ep.interval_upper)
        for ep in executed_known
        if ep.point_prediction is not None
        and ep.observed_value is not None
        and ep.interval_lower is not None
        and ep.interval_upper is not None
        and not ep.rolled_back
    ]
    s_count = len(scalar_tuples)
    abs_errors = [abs(pt - obs) for pt, obs, _, _ in scalar_tuples]
    sq_errors = [(pt - obs) ** 2 for pt, obs, _, _ in scalar_tuples]
    widths = [hi - lo for _, _, lo, hi in scalar_tuples]
    covered_count = sum(1 for _, obs, lo, hi in scalar_tuples if lo <= obs <= hi)
    mae = math.fsum(abs_errors) / s_count if s_count else None
    rmse = math.sqrt(math.fsum(sq_errors) / s_count) if s_count else None
    int_cov = covered_count / s_count if s_count else None
    ic_low, ic_high = _wilson_95(covered_count, s_count)
    mean_width = math.fsum(widths) / s_count if s_count else None

    cal_tuples = [
        (ep.predicted_recovery_probability, 1.0 if ep.recovered else 0.0)
        for ep in executed_known
        if ep.predicted_recovery_probability is not None and ep.recovered is not None
    ]
    c_count = len(cal_tuples)
    brier = (
        math.fsum((prob - actual) ** 2 for prob, actual in cal_tuples) / c_count
        if c_count
        else None
    )
    ece = (
        abs(
            math.fsum(prob for prob, _ in cal_tuples) / c_count
            - math.fsum(actual for _, actual in cal_tuples) / c_count
        )
        if c_count
        else None
    )

    return (
        ArmOperationalMetrics(
            arm=arm,
            recovery=RecoveryMetrics(
                executed_denominator=exec_denom,
                recovered_count=recovered_count,
                recovery_rate=rec_rate,
                wilson_95_lower=rec_low,
                wilson_95_upper=rec_high,
                mean_recovery_seconds=mean_rec_sec,
                unknown_outcome_count=unknown_count,
            ),
            recurrence=RecurrenceMetrics(
                completed_window_denominator=rec_win_denom,
                recurred_count=recurred_count,
                recurrence_rate=recurrence_rate,
                wilson_95_lower=recur_low,
                wilson_95_upper=recur_high,
                censored_incomplete_window_count=censored_rec,
            ),
            rollback_and_side_effects=RollbackAndSideEffectMetrics(
                executed_denominator=exec_denom,
                rolled_back_count=rolled_back_count,
                rollback_rate=rollback_rate,
                rollback_wilson_95_upper=rb_upper,
                side_effect_count=side_effect_count,
                side_effect_rate=side_effect_rate,
                side_effect_wilson_95_upper=se_upper,
                policy_escape_count=policy_escape_count,
            ),
            abstention_and_coverage=AbstentionAndCoverageMetrics(
                independent_episode_denominator=ind_denom,
                recommended_count=recommended_count,
                recommendation_coverage=cov_rate,
                coverage_wilson_95_lower=cov_low,
                coverage_wilson_95_upper=cov_high,
                abstained_count=abstained_count,
                abstention_rate=abs_rate,
                abstention_wilson_95_lower=abs_low,
                abstention_wilson_95_upper=abs_high,
                conditional_success_rate=cond_success,
            ),
            prediction_and_calibration=PredictionAndCalibrationMetrics(
                scored_scalar_count=s_count,
                mean_absolute_error=mae,
                root_mean_squared_error=rmse,
                interval_coverage=int_cov,
                interval_coverage_wilson_95_lower=ic_low,
                interval_coverage_wilson_95_upper=ic_high,
                mean_interval_width=mean_width,
                calibration_sample_count=c_count,
                brier_score=brier,
                expected_calibration_error=ece,
            ),
            sample_counts=SampleCountAndUncertaintySummary(
                raw_observation_count=raw_count,
                excluded_retry_or_replay_count=retry_excluded,
                excluded_duplicate_group_count=dup_excluded,
                excluded_time_separation_count=time_excluded,
                independent_episode_count=ind_denom,
                unknown_outcome_count=unknown_count,
            ),
        ),
        independent,
    )


def evaluate_operational_learning_effects(
    *,
    scope: QualificationVenueSelection,
    gates: PredeclaredLearningEvaluationGates,
    provenance: FrozenProvenanceQualification,
    t1_shadow_intake: FrozenT1ShadowIntakeSummary,
    episodes: Sequence[OperationalLearningEpisode],
    claim_policy_effect: bool = False,
) -> OperationalLearningEffectReport:
    """Evaluate baseline/challenger cohorts against predeclared SLO and safety gates."""
    if scope.slo_revision != gates.slo_revision or (
        scope.safety_budget_revision != gates.safety_budget_revision
    ):
        raise ValueError("scope and predeclared gates MUST bind the same SLO and safety revisions")
    seen_incidents: set[str] = set()
    seen_independence: set[str] = set()
    seen_common_cause: set[str] = set()
    seen_idempotency: set[str] = set()
    baseline_eps = [ep for ep in episodes if ep.arm == "baseline"]
    challenger_eps = [ep for ep in episodes if ep.arm == "challenger"]
    baseline_metrics, ind_base = _evaluate_arm(
        "baseline",
        baseline_eps,
        gates=gates,
        seen_incidents=seen_incidents,
        seen_independence=seen_independence,
        seen_common_cause=seen_common_cause,
        seen_idempotency=seen_idempotency,
    )
    challenger_metrics, ind_chal = _evaluate_arm(
        "challenger",
        challenger_eps,
        gates=gates,
        seen_incidents=seen_incidents,
        seen_independence=seen_independence,
        seen_common_cause=seen_common_cause,
        seen_idempotency=seen_idempotency,
    )
    can_claim_policy_effect = bool(
        ind_base
        and ind_chal
        and all(
            ep.intervention_completed
            and ep.execution_mode == "enforce"
            and ep.propensity_overlap_verified
            for ep in (*ind_base, *ind_chal)
        )
    )
    if claim_policy_effect and not can_claim_policy_effect:
        raise ValueError(
            "policy effect cannot be claimed from unexecuted candidates or shadow predictions "
            "without selection/overlap evidence"
        )
    failures: list[str] = []
    for arm_metrics in (baseline_metrics, challenger_metrics):
        prefix = arm_metrics.arm
        if arm_metrics.sample_counts.independent_episode_count < (
            gates.min_independent_episodes_per_arm
        ):
            failures.append(f"{prefix}:insufficient_independent_episodes")
        if arm_metrics.rollback_and_side_effects.side_effect_count > gates.max_side_effect_count:
            failures.append(f"{prefix}:side_effect_budget_exceeded")
        if (
            arm_metrics.rollback_and_side_effects.policy_escape_count
            > gates.max_policy_escape_count
        ):
            failures.append(f"{prefix}:policy_escape_budget_exceeded")
    c_rec = challenger_metrics.recovery.recovery_rate
    if c_rec is not None and c_rec < gates.min_recovery_rate:
        failures.append("challenger:recovery_rate_below_slo")
    c_recur = challenger_metrics.recurrence.recurrence_rate
    if c_recur is not None and c_recur > gates.max_recurrence_rate:
        failures.append("challenger:recurrence_rate_above_slo")
    c_rb = challenger_metrics.rollback_and_side_effects.rollback_rate
    if c_rb is not None and c_rb > gates.max_rollback_rate:
        failures.append("challenger:rollback_rate_above_budget")
    c_mae = challenger_metrics.prediction_and_calibration.mean_absolute_error
    if c_mae is not None and c_mae > gates.max_mean_absolute_error:
        failures.append("challenger:mae_above_gate")
    c_brier = challenger_metrics.prediction_and_calibration.brier_score
    if c_brier is not None and c_brier > gates.max_brier_score:
        failures.append("challenger:brier_score_above_gate")
    c_cov = challenger_metrics.prediction_and_calibration.interval_coverage
    if c_cov is not None and c_cov < gates.min_interval_coverage:
        failures.append("challenger:interval_coverage_below_gate")
    return OperationalLearningEffectReport(
        scope=scope,
        gates=gates,
        provenance=provenance,
        t1_shadow_intake=t1_shadow_intake,
        baseline=baseline_metrics,
        challenger=challenger_metrics,
        gates_passed=not failures,
        gate_failures=tuple(failures),
        policy_effect_claimed=bool(claim_policy_effect and can_claim_policy_effect),
    )
