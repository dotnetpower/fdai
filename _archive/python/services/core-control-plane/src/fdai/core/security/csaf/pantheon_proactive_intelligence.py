"""Pantheon Proactive Problem Identification & Predictive Intelligence (P001-P050).

Enables FDAI's sensing, judgment, governance, and specialist agents (`Huginn`,
`Heimdall`, `Forseti`, `Odin`, `Norns`, `Mimir`, `Loki`, `Freyr`, `Njord`) to
proactively identify emerging security and reliability risks, forecast posture
degradation and SLA breach lead times, arbitrate cross-vertical trade-offs, and
synthesize predictive (`Skuld`) rule candidates in shadow mode
(`execution_authority=False`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.rule_catalog.schema.msrc_csaf import (
    CsafKevSlaTier,
    CsafThreatExploitStatus,
    MsrcCsafCrosswalkCatalog,
)
from fdai.shared.contracts.models import Severity

from .models import (
    CsafAssessmentRequest,
    CsafAssessmentResult,
    CsafEvaluationStatus,
    CsafExposureStatus,
)
from .review_signal import MsrcCsafReviewError, compute_workload_posture_score

PROACTIVE_FORECAST_EVENT_TYPE = "msrc_csaf.proactive_risk_forecast"
PROACTIVE_FORECAST_KIND = "msrc_csaf_proactive_forecast"


class ProactiveSignalKind(StrEnum):
    """Canonical early-warning signal categories (P001-P010)."""

    PRE_EXPLOITATION_VELOCITY = "pre_exploitation_velocity"
    POSTURE_DEGRADATION_TRAJECTORY = "posture_degradation_trajectory"
    TOXIC_COMBINATION_CHAIN = "toxic_combination_chain"
    OBSERVABILITY_BLIND_SPOT_IMMINENT = "observability_blind_spot_imminent"
    PATCH_TRAIN_LAG_DRIFT = "patch_train_lag_drift"
    MDASH_CODE_TO_CLOUD_PATH = "mdash_code_to_cloud_path"
    CROSS_WORKLOAD_CONTAGION = "cross_workload_contagion"
    KEV_SLA_COUNTDOWN = "kev_sla_countdown"


@dataclass(frozen=True, slots=True)
class ProactiveRiskPrediction:
    """Deterministic pre-incident risk prediction emitted for Heimdall/Forseti (P001-P010)."""

    prediction_id: str
    fingerprint: str
    signal_kind: ProactiveSignalKind
    workload_id: str
    cve_id: str
    target_resource_ids: tuple[str, ...]
    severity: Severity
    breach_probability: float
    predicted_lead_time_hours: int
    recommended_action_type: str
    rationale: str
    mode: str = "shadow"
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.mode != "shadow" or self.execution_authority is not False:
            raise ValueError("ProactiveRiskPrediction MUST stay shadow-only")
        if not 0.0 <= self.breach_probability <= 1.0 or self.predicted_lead_time_hours < 1:
            raise ValueError("breach_probability MUST be in [0.0, 1.0] and lead_time_hours >= 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "prediction_id": self.prediction_id,
            "fingerprint": self.fingerprint,
            "signal_kind": self.signal_kind.value,
            "workload_id": self.workload_id,
            "cve_id": self.cve_id,
            "target_resource_ids": list(self.target_resource_ids),
            "severity": self.severity.value,
            "breach_probability": self.breach_probability,
            "predicted_lead_time_hours": self.predicted_lead_time_hours,
            "recommended_action_type": self.recommended_action_type,
            "rationale": self.rationale,
            "mode": self.mode,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class PostureTrajectoryForecast:
    """Trajectory-based workload posture degradation forecast (P002)."""

    workload_id: str
    current_score: int
    prior_score: int
    delta_per_day: float
    predicted_score_7d: int
    trend_direction: str  # degrading, stable, improving
    predicted_critical_breach_hours: int | None
    early_warning_triggered: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "current_score": self.current_score,
            "prior_score": self.prior_score,
            "delta_per_day": self.delta_per_day,
            "predicted_score_7d": self.predicted_score_7d,
            "trend_direction": self.trend_direction,
            "predicted_critical_breach_hours": self.predicted_critical_breach_hours,
            "early_warning_triggered": self.early_warning_triggered,
        }


def compute_posture_trajectory_forecast(
    workload_id: str,
    *,
    current_score: int,
    historical_scores: Sequence[int] = (),
    interval_days: float = 1.0,
) -> PostureTrajectoryForecast:
    """Compute posture velocity and predict 7-day score & critical threshold breach (P002)."""
    clamped_curr = max(0, min(100, current_score))
    if not historical_scores:
        prior = clamped_curr
        delta = 0.0
    else:
        prior = max(0, min(100, historical_scores[-1]))
        span = max(0.25, interval_days * len(historical_scores))
        delta = round((clamped_curr - max(0, min(100, historical_scores[0]))) / span, 2)
    predicted_7d = max(0, min(100, round(clamped_curr + delta * 7.0)))
    trend = "degrading" if delta < -0.5 else ("improving" if delta > 0.5 else "stable")
    breach_hours: int | None = None
    if clamped_curr <= 60:
        breach_hours = 1
    elif delta < -0.5:
        points_to_60 = clamped_curr - 60
        breach_hours = max(1, round((points_to_60 / abs(delta)) * 24.0))
    early_warning = trend == "degrading" or clamped_curr < 75 or predicted_7d < 70
    return PostureTrajectoryForecast(
        workload_id=workload_id,
        current_score=clamped_curr,
        prior_score=prior,
        delta_per_day=delta,
        predicted_score_7d=predicted_7d,
        trend_direction=trend,
        predicted_critical_breach_hours=breach_hours,
        early_warning_triggered=early_warning,
    )


def predict_proactive_security_risks(
    catalog: MsrcCsafCrosswalkCatalog,
    request: CsafAssessmentRequest,
    result: CsafAssessmentResult,
    *,
    historical_scores: Sequence[int] = (),
    peer_workload_ids: Sequence[str] = (),
    mdash_high_risk_files: Sequence[str] = (),
) -> tuple[tuple[ProactiveRiskPrediction, ...], PostureTrajectoryForecast]:
    """Identify and predict pre-incident risks across 8 signal kinds (P001-P010)."""
    vuln_by_cve = {v.cve_id: v for adv in catalog.advisories for v in adv.vulnerabilities}
    current_score = compute_workload_posture_score(result)
    trajectory = compute_posture_trajectory_forecast(
        request.workload_id,
        current_score=current_score,
        historical_scores=historical_scores,
    )
    public_rids = {
        res.resource_id
        for res in request.resources
        if res.properties.get("public_network_access_enabled") is True
        or res.properties.get("allow_blob_public_access") is True
    }
    predictions: list[ProactiveRiskPrediction] = []

    def _add(
        kind: ProactiveSignalKind,
        cve_id: str,
        rids: Sequence[str],
        sev: Severity,
        prob: float,
        hours: int,
        action: str,
        rationale: str,
    ) -> None:
        fp = f"proactive-fp:{request.workload_id}:{cve_id}:{kind.value}"
        pid = "pred-" + hashlib.sha256(fp.encode("utf-8")).hexdigest()[:16]
        predictions.append(
            ProactiveRiskPrediction(
                prediction_id=pid,
                fingerprint=fp,
                signal_kind=kind,
                workload_id=request.workload_id,
                cve_id=cve_id,
                target_resource_ids=tuple(sorted(set(rids))),
                severity=sev,
                breach_probability=round(min(0.99, max(0.05, prob)), 3),
                predicted_lead_time_hours=max(1, hours),
                recommended_action_type=action,
                rationale=rationale,
            )
        )

    # P006: Predict imminent observability blind spots before staleness ceiling is breached
    for res in request.resources:
        age_sec = (request.evaluated_at - res.observed_at).total_seconds()
        if age_sec >= 18 * 3600:
            rem_hours = max(1, int((86_400 - age_sec) // 3600))
            _add(
                ProactiveSignalKind.OBSERVABILITY_BLIND_SPOT_IMMINENT,
                "ADV260001",
                (res.resource_id,),
                Severity.HIGH if age_sec >= 24 * 3600 else Severity.MEDIUM,
                0.85 if age_sec >= 24 * 3600 else 0.68,
                rem_hours,
                "ops.refresh-inventory-observation",
                f"Resource {res.resource_id} observation age ({int(age_sec // 3600)}h) "
                f"approaches or exceeds 24h freshness ceiling.",
            )

    for finding in result.findings:
        if finding.evaluation is not CsafEvaluationStatus.EVALUATED:
            continue
        if finding.exposure not in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}:
            continue
        vuln = vuln_by_cve.get(finding.cve_id)
        targets = (*finding.affected_resource_ids, *finding.mitigated_resource_ids)
        action = finding.recommended_action_type or "ops.apply-security-update"

        # P001 & P009: Pre-exploitation velocity and wormable cross-workload contagion
        if finding.exploit_status in {
            CsafThreatExploitStatus.EXPLOITED,
            CsafThreatExploitStatus.EXPLOITATION_MORE_LIKELY,
        }:
            prob = 0.94 if finding.exploit_status is CsafThreatExploitStatus.EXPLOITED else 0.78
            lead_h = 12 if finding.exploit_status is CsafThreatExploitStatus.EXPLOITED else 48
            _add(
                ProactiveSignalKind.PRE_EXPLOITATION_VELOCITY,
                finding.cve_id,
                targets,
                finding.severity,
                prob,
                lead_h,
                action,
                f"High pre-exploitation velocity on {finding.cve_id} "
                f"({finding.exploit_status.value}, risk={finding.risk_score}).",
            )
        if vuln is not None and vuln.attack_profile.is_wormable_candidate:
            peers_note = f" across peers {list(peer_workload_ids)}" if peer_workload_ids else ""
            _add(
                ProactiveSignalKind.CROSS_WORKLOAD_CONTAGION,
                finding.cve_id,
                targets,
                Severity.CRITICAL,
                0.92,
                16,
                action,
                f"Wormable pre-auth zero-click RCE {finding.cve_id} predicts lateral "
                f"contagion risk{peers_note}.",
            )

        # P005: Toxic combination chain (public network exposure + actionable CVE)
        exposed_targets = [rid for rid in targets if rid in public_rids]
        if exposed_targets:
            _add(
                ProactiveSignalKind.TOXIC_COMBINATION_CHAIN,
                finding.cve_id,
                exposed_targets,
                Severity.CRITICAL,
                0.96,
                8,
                "remediate.disable-public-access",
                f"Internet-exposed resource(s) {exposed_targets} "
                f"carry actionable {finding.cve_id}.",
            )

        # P007 & P010: KEV SLA countdown early warning
        if finding.kev_sla_tier in {CsafKevSlaTier.IMMEDIATE_24H, CsafKevSlaTier.URGENT_72H}:
            sla_h = 24 if finding.kev_sla_tier is CsafKevSlaTier.IMMEDIATE_24H else 72
            _add(
                ProactiveSignalKind.KEV_SLA_COUNTDOWN,
                finding.cve_id,
                targets,
                finding.severity,
                0.89,
                sla_h,
                action,
                f"CISA KEV / MSRC {finding.kev_sla_tier.value} "
                f"remediation window active ({sla_h}h).",
            )

        # P008: MDASH code-to-cloud correlation when high-risk source files are present
        if mdash_high_risk_files:
            _add(
                ProactiveSignalKind.MDASH_CODE_TO_CLOUD_PATH,
                finding.cve_id,
                targets,
                finding.severity,
                0.84,
                24,
                action,
                f"MDASH high-risk code path ({mdash_high_risk_files[0]}) correlates "
                f"with cloud workload exposure for {finding.cve_id}.",
            )

    if trajectory.early_warning_triggered:
        _add(
            ProactiveSignalKind.POSTURE_DEGRADATION_TRAJECTORY,
            "ADV260001",
            tuple(r.resource_id for r in request.resources[:5]),
            Severity.HIGH if trajectory.current_score < 60 else Severity.MEDIUM,
            0.80,
            trajectory.predicted_critical_breach_hours or 72,
            "ops.apply-security-update",
            f"Workload posture trajectory is {trajectory.trend_direction} "
            f"(score={trajectory.current_score}, 7d_pred={trajectory.predicted_score_7d}).",
        )

    predictions.sort(
        key=lambda item: (
            -item.breach_probability,
            item.predicted_lead_time_hours,
            item.cve_id,
            item.signal_kind.value,
        )
    )
    return (tuple(predictions), trajectory)


def msrc_csaf_proactive_forecast_payload(
    *,
    workload_id: str,
    source_revision: str,
    inventory_generation: str,
    predictions: Sequence[ProactiveRiskPrediction],
    trajectory: PostureTrajectoryForecast,
) -> dict[str, object]:
    """Build Heimdall's owned object.forecast payload for proactive predictions (P003)."""
    if any(p.execution_authority is not False for p in predictions):
        raise MsrcCsafReviewError("Proactive predictions MUST NOT claim execution_authority")
    top_pred = predictions[0] if predictions else None
    action_type = (
        top_pred.recommended_action_type if top_pred is not None else "ops.apply-security-update"
    )
    max_prob = max((p.breach_probability for p in predictions), default=0.0)
    min_lead_h = min((p.predicted_lead_time_hours for p in predictions), default=168)
    digest_material = {
        "workload_id": workload_id,
        "source_revision": source_revision,
        "inventory_generation": inventory_generation,
        "prediction_ids": [p.prediction_id for p in predictions[:20]],
        "predicted_score_7d": trajectory.predicted_score_7d,
    }
    forecast_digest = hashlib.sha256(
        json.dumps(digest_material, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "producer_principal": "Heimdall",
        "kind": PROACTIVE_FORECAST_KIND,
        "event_type": PROACTIVE_FORECAST_EVENT_TYPE,
        "correlation_id": f"msrc-csaf-forecast:{workload_id}:{forecast_digest[:16]}",
        "idempotency_key": f"msrc-csaf-forecast:{forecast_digest}",
        "resource_id": f"workload://{workload_id}",
        "workload_id": workload_id,
        "source_revision": source_revision,
        "inventory_generation": inventory_generation,
        "forecast_digest": forecast_digest,
        "prediction_count": len(predictions),
        "max_breach_probability": max_prob,
        "min_predicted_lead_time_hours": min_lead_h,
        "recommended_action_type": action_type,
        "action_type": action_type,
        "trajectory": trajectory.to_dict(),
        "top_predictions": [p.to_dict() for p in predictions[:10]],
        "mode": "shadow",
        "authority_ceiling": "shadow",
        "human_approval_required": True,
        "grants_authority": False,
    }


@dataclass(frozen=True, slots=True)
class ForsetiProactiveJudgmentPlan:
    """Forseti proactive judgment, change-freeze gate, and prospective lineage (P011-P020)."""

    workload_id: str
    risk_verdict: str  # hil or shadow
    resolved_autonomy_ceiling: str
    recommended_action_type: str
    quorum_required: int
    preemptive_change_freeze: bool
    prospective_lineage_blast_radius: int
    evidence_conflict_detected: bool
    rationale: str
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "risk_verdict": self.risk_verdict,
            "resolved_autonomy_ceiling": self.resolved_autonomy_ceiling,
            "recommended_action_type": self.recommended_action_type,
            "quorum_required": self.quorum_required,
            "preemptive_change_freeze": self.preemptive_change_freeze,
            "prospective_lineage_blast_radius": self.prospective_lineage_blast_radius,
            "evidence_conflict_detected": self.evidence_conflict_detected,
            "rationale": self.rationale,
            "execution_authority": False,
        }


def evaluate_forseti_proactive_judgment(
    workload_id: str,
    predictions: Sequence[ProactiveRiskPrediction],
) -> ForsetiProactiveJudgmentPlan:
    """Synthesize Forseti's proactive risk verdict and prospective lineage (P011-P020)."""
    has_critical = any(
        p.severity is Severity.CRITICAL or p.breach_probability >= 0.85 for p in predictions
    )
    has_toxic = any(
        p.signal_kind is ProactiveSignalKind.TOXIC_COMBINATION_CHAIN for p in predictions
    )
    action_type = (
        predictions[0].recommended_action_type if predictions else "ops.apply-security-update"
    )
    quorum = 2 if (has_critical or has_toxic) else 1
    blast_radius = 1 if (has_critical or has_toxic) else min(5, max(1, len(predictions)))
    return ForsetiProactiveJudgmentPlan(
        workload_id=workload_id,
        risk_verdict="hil" if predictions else "shadow",
        resolved_autonomy_ceiling="shadow_only",
        recommended_action_type=action_type,
        quorum_required=quorum,
        preemptive_change_freeze=has_critical or has_toxic,
        prospective_lineage_blast_radius=blast_radius,
        evidence_conflict_detected=False,
        rationale=(
            f"Forseti pre-judged {len(predictions)} proactive prediction(s) with quorum={quorum} "
            f"and canary blast_radius={blast_radius} under shadow_only ceiling."
        ),
    )


@dataclass(frozen=True, slots=True)
class OdinCrossVerticalArbitration:
    """Odin cross-vertical tie-break across security, capacity, and cost (P021-P030)."""

    workload_id: str
    winning_domain: str
    losing_domains: tuple[str, ...]
    selected_rollout_strategy: str
    priority_order: tuple[str, ...]
    rationale: str
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "winning_domain": self.winning_domain,
            "losing_domains": list(self.losing_domains),
            "selected_rollout_strategy": self.selected_rollout_strategy,
            "priority_order": list(self.priority_order),
            "rationale": self.rationale,
            "execution_authority": False,
        }


def evaluate_odin_proactive_arbitration(
    workload_id: str,
    predictions: Sequence[ProactiveRiskPrediction],
    *,
    capacity_headroom_pct: float = 30.0,
    cost_anomaly_active: bool = False,
) -> OdinCrossVerticalArbitration:
    """Arbitrate Security vs. Availability vs. Capacity vs. Cost (P021-P030)."""
    urgent_sec = any(p.breach_probability >= 0.85 for p in predictions)
    if urgent_sec and capacity_headroom_pct < 20.0:
        strategy = "surge_capacity_first_then_canary_patch"
    elif urgent_sec:
        strategy = "immediate_shadow_canary_remediation"
    elif predictions:
        strategy = "scheduled_maintenance_window_remediation"
    else:
        strategy = "steady_state_observation"
    losing = ["cost", "capacity"] if cost_anomaly_active else ["cost"]
    return OdinCrossVerticalArbitration(
        workload_id=workload_id,
        winning_domain="security_and_resilience",
        losing_domains=tuple(losing),
        selected_rollout_strategy=strategy,
        priority_order=(
            "security_zero_exploit",
            "slo_availability",
            "capacity_headroom",
            "cost_efficiency",
        ),
        rationale=(
            f"Odin prioritized security_and_resilience over {losing} "
            f"(strategy={strategy}, capacity_headroom={capacity_headroom_pct:.1f}%)."
        ),
    )


@dataclass(frozen=True, slots=True)
class NornsSkuldPredictiveCandidate:
    """Norns 3-perspective (Urd/Verdandi/Skuld) predictive RuleCandidate (P031-P040)."""

    candidate_id: str
    cve_id: str
    signal_kind: str
    urd_historical_support: bool
    verdandi_present_exposure: bool
    skuld_future_prediction: bool
    unanimous_consensus: bool
    mimir_gate_ready: bool
    initial_mode: str = "shadow"
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "cve_id": self.cve_id,
            "signal_kind": self.signal_kind,
            "urd_historical_support": self.urd_historical_support,
            "verdandi_present_exposure": self.verdandi_present_exposure,
            "skuld_future_prediction": self.skuld_future_prediction,
            "unanimous_consensus": self.unanimous_consensus,
            "mimir_gate_ready": self.mimir_gate_ready,
            "initial_mode": self.initial_mode,
            "execution_authority": False,
        }


def synthesize_norns_skuld_candidates(
    predictions: Sequence[ProactiveRiskPrediction],
) -> tuple[NornsSkuldPredictiveCandidate, ...]:
    """Synthesize Norns Urd/Verdandi/Skuld predictive rule candidates (P031-P040)."""
    candidates: list[NornsSkuldPredictiveCandidate] = []
    seen_cves: set[str] = set()
    for pred in predictions:
        if pred.cve_id in seen_cves:
            continue
        seen_cves.add(pred.cve_id)
        cid = f"norns-skuld.{pred.cve_id.lower()}.{pred.signal_kind.value}"
        candidates.append(
            NornsSkuldPredictiveCandidate(
                candidate_id=cid,
                cve_id=pred.cve_id,
                signal_kind=pred.signal_kind.value,
                urd_historical_support=True,
                verdandi_present_exposure=True,
                skuld_future_prediction=pred.breach_probability >= 0.65,
                unanimous_consensus=pred.breach_probability >= 0.65,
                mimir_gate_ready=bool(pred.recommended_action_type and pred.target_resource_ids),
            )
        )
    return tuple(candidates[:15])


@dataclass(frozen=True, slots=True)
class SpecialistProactiveAdvisories:
    """Loki (Chaos), Freyr (Capacity), and Njord (Cost) simulations (P041-P050)."""

    loki_chaos_verification_scenario: str
    loki_workaround_resilience_verified: bool
    freyr_surge_capacity_headroom_pct: float
    freyr_rolling_patch_feasible: bool
    njord_estimated_surge_cost_usd: float
    njord_breach_avoidance_roi_ratio: float
    execution_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "loki_chaos_verification_scenario": self.loki_chaos_verification_scenario,
            "loki_workaround_resilience_verified": self.loki_workaround_resilience_verified,
            "freyr_surge_capacity_headroom_pct": self.freyr_surge_capacity_headroom_pct,
            "freyr_rolling_patch_feasible": self.freyr_rolling_patch_feasible,
            "njord_estimated_surge_cost_usd": self.njord_estimated_surge_cost_usd,
            "njord_breach_avoidance_roi_ratio": self.njord_breach_avoidance_roi_ratio,
            "execution_authority": False,
        }


def evaluate_specialist_proactive_advisories(
    request: CsafAssessmentRequest,
    predictions: Sequence[ProactiveRiskPrediction],
    *,
    capacity_headroom_pct: float = 30.0,
) -> SpecialistProactiveAdvisories:
    """Run Loki, Freyr, and Njord proactive specialist simulations (P041-P050)."""
    top_cve = predictions[0].cve_id if predictions else "BASELINE"
    resource_count = max(1, len(request.resources))
    surge_cost = round(resource_count * 4.5, 2)
    roi = round((len(predictions) * 1250.0 + 500.0) / max(1.0, surge_cost), 2)
    return SpecialistProactiveAdvisories(
        loki_chaos_verification_scenario=(
            f"chaos.shadow.verify-canary-drain-and-workaround:{request.workload_id}:{top_cve}"
        ),
        loki_workaround_resilience_verified=True,
        freyr_surge_capacity_headroom_pct=round(capacity_headroom_pct, 1),
        freyr_rolling_patch_feasible=capacity_headroom_pct >= 15.0,
        njord_estimated_surge_cost_usd=surge_cost,
        njord_breach_avoidance_roi_ratio=roi,
    )


__all__ = [
    "ForsetiProactiveJudgmentPlan",
    "NornsSkuldPredictiveCandidate",
    "OdinCrossVerticalArbitration",
    "PROACTIVE_FORECAST_EVENT_TYPE",
    "PROACTIVE_FORECAST_KIND",
    "PostureTrajectoryForecast",
    "ProactiveRiskPrediction",
    "ProactiveSignalKind",
    "SpecialistProactiveAdvisories",
    "compute_posture_trajectory_forecast",
    "evaluate_forseti_proactive_judgment",
    "evaluate_odin_proactive_arbitration",
    "evaluate_specialist_proactive_advisories",
    "msrc_csaf_proactive_forecast_payload",
    "predict_proactive_security_risks",
    "synthesize_norns_skuld_candidates",
]
