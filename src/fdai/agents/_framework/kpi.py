"""KPI collector primitives (Wave 8).

Every pantheon agent MUST emit its declared KPIs into the measurement
pipeline (`docs/roadmap/architecture/goals-and-metrics.md`). Wave 8 ships a simple
in-memory collector so shadow-mode promotion gates can evaluate
against the KPI table in `agent-pantheon.md` \u00a74.2 without a real
telemetry backend. Fork adapters swap in the actual sink (Application
Insights, Prometheus).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

#: Cap on retained KPI samples in the in-memory ring. An agent emits KPIs for
#: the whole process lifetime, so an unbounded list would leak and make
#: latest() an ever-slower O(n) scan. The most-recent-per-metric value is
#: preserved separately (see KpiCollector._latest), so the ring can drop old
#: samples without losing the value the promotion gate reads.
_MAX_SAMPLES = 10_000


class KpiEvidenceState(StrEnum):
    MEASURED = "measured"
    NOT_MEASURED = "not_measured"
    NOT_CONNECTED = "not_connected"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    NOT_APPLICABLE = "not_applicable"


DECLARED_AGENT_KPIS: dict[str, tuple[str, ...]] = {
    "Odin": (
        "conflict_resolution_time_seconds",
        "portfolio_target_attainment_ratio",
        "tie_break_recurrence_rate",
    ),
    "Thor": (
        "execution_success_rate",
        "execution_latency_p99_seconds",
        "rollback_trigger_rate",
        "race_failure_rate",
    ),
    "Forseti": (
        "verdict_accuracy",
        "t2_escalation_rate",
        "mixed_model_disagreement_rate",
        "grounding_missing_rate",
    ),
    "Huginn": (
        "event_processing_latency_p99_seconds",
        "discovery_delivery_latency_p99_seconds",
        "dedup_accuracy",
        "schema_match_failure_rate",
        "discovery_cursor_lag_seconds",
    ),
    "Heimdall": (
        "anomaly_precision",
        "anomaly_recall",
        "forecast_mape",
        "discovery_coverage_detection_rate",
        "false_positive_rate",
        "missed_critical_rate",
        "stale_inventory_detection_delay_seconds",
    ),
    "Vidar": (
        "rollback_success_rate",
        "mttr_seconds",
        "rollback_path_validation_failure_rate",
    ),
    "Var": (
        "hil_sla_compliance_rate",
        "quorum_compliance_rate",
        "expiry_rate",
        "repeated_escalation_rate",
    ),
    "Bragi": (
        "routing_accuracy",
        "session_satisfaction_rate",
        "handoff_rate",
    ),
    "Saga": (
        "audit_chain_integrity_rate",
        "replay_success_rate",
        "audit_gap_detection_rate",
    ),
    "Mimir": (
        "rule_freshness_score",
        "promotion_pass_rate",
        "shadow_failure_rate",
        "stale_rule_ratio",
    ),
    "Muninn": (
        "context_fetch_p99_seconds",
        "cache_hit_rate",
        "cache_miss_recomputation_seconds",
    ),
    "Norns": (
        "rule_candidate_adoption_rate",
        "pattern_validity_rate",
        "false_pattern_rate",
    ),
    "Njord": (
        "cost_forecast_mape",
        "savings_realized_usd",
        "budget_breach_miss_rate",
    ),
    "Freyr": (
        "capacity_forecast_error",
        "over_provisioning_rate",
        "under_provisioning_rate",
        "scale_race_rate",
        "throttle_event_rate",
    ),
    "Loki": (
        "blast_radius_adherence_rate",
        "resilience_improvement_delta",
        "unplanned_side_effect_rate",
        "experiment_failure_rate",
    ),
}


@dataclass
class KpiSample:
    agent: str
    metric: str
    value: float | None
    evidence_state: KpiEvidenceState = KpiEvidenceState.MEASURED
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class KpiCollector:
    """In-memory KPI sink. Deterministic; test-friendly.

    ``samples`` is a bounded ring (recent history for ``all_for``); the
    authoritative most-recent value per ``(agent, metric)`` lives in
    ``_latest`` so :meth:`latest` is O(1) and correct even after the ring
    has evicted that sample.
    """

    samples: deque[KpiSample] = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    _latest: dict[tuple[str, str], KpiSample] = field(default_factory=dict)

    def record(
        self,
        *,
        agent: str,
        metric: str,
        value: float | None,
        evidence_state: KpiEvidenceState | str = KpiEvidenceState.MEASURED,
        tags: dict[str, str] | None = None,
    ) -> KpiSample:
        resolved_state = KpiEvidenceState(evidence_state)
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError("KPI value MUST be finite when measured")
        if resolved_state is KpiEvidenceState.MEASURED and value is None:
            raise ValueError("measured KPI MUST carry a value")
        if resolved_state is not KpiEvidenceState.MEASURED and value is not None:
            raise ValueError("unavailable KPI MUST NOT carry a value")
        sample = KpiSample(
            agent=agent,
            metric=metric,
            value=float(value) if value is not None else None,
            evidence_state=resolved_state,
            tags=dict(tags or {}),
        )
        self.samples.append(sample)
        self._latest[(agent, metric)] = sample
        return sample

    def report_declared(
        self,
        *,
        agent: str,
        values: Mapping[str, float] | None = None,
        unavailable_state: KpiEvidenceState = KpiEvidenceState.NOT_MEASURED,
        tags: dict[str, str] | None = None,
    ) -> tuple[KpiSample, ...]:
        declared = DECLARED_AGENT_KPIS.get(agent)
        if declared is None:
            raise ValueError(f"unknown KPI agent: {agent}")
        supplied = dict(values or {})
        unknown = set(supplied) - set(declared)
        if unknown:
            raise ValueError(f"undeclared KPI metrics for {agent}: {sorted(unknown)}")
        samples: list[KpiSample] = []
        for metric in declared:
            if metric in supplied:
                samples.append(
                    self.record(
                        agent=agent,
                        metric=metric,
                        value=supplied[metric],
                        evidence_state=KpiEvidenceState.MEASURED,
                        tags=tags,
                    )
                )
                continue
            existing = self.latest(agent=agent, metric=metric)
            if existing is not None and existing.evidence_state is KpiEvidenceState.MEASURED:
                samples.append(existing)
                continue
            samples.append(
                self.record(
                    agent=agent,
                    metric=metric,
                    value=None,
                    evidence_state=unavailable_state,
                    tags=tags,
                )
            )
        return tuple(samples)

    def latest(self, *, agent: str, metric: str) -> KpiSample | None:
        return self._latest.get((agent, metric))

    def all_for(self, agent: str) -> tuple[KpiSample, ...]:
        return tuple(s for s in self.samples if s.agent == agent)

    def coverage(self) -> dict[str, dict[str, int]]:
        return {
            agent: {
                "declared": len(metrics),
                "reported": sum(
                    self.latest(agent=agent, metric=metric) is not None for metric in metrics
                ),
                "measured": sum(
                    (sample := self.latest(agent=agent, metric=metric)) is not None
                    and sample.evidence_state is KpiEvidenceState.MEASURED
                    for metric in metrics
                ),
            }
            for agent, metrics in DECLARED_AGENT_KPIS.items()
        }


@dataclass
class PromotionGateThreshold:
    metric: str
    min: float | None = None
    max: float | None = None

    def evaluate(self, sample: KpiSample | None) -> bool:
        if sample is None or sample.value is None:
            return False
        if self.min is not None and sample.value < self.min:
            return False
        if self.max is not None and sample.value > self.max:
            return False
        return True


@dataclass
class PromotionGate:
    workflow_id: str
    thresholds: tuple[PromotionGateThreshold, ...]

    def evaluate(self, collector: KpiCollector) -> tuple[bool, dict[str, bool]]:
        outcomes: dict[str, bool] = {}
        overall = True
        for th in self.thresholds:
            agent, metric = th.metric.split(".", 1) if "." in th.metric else ("", th.metric)
            sample = collector.latest(agent=agent, metric=metric) if agent else None
            passed = th.evaluate(sample)
            outcomes[th.metric] = passed
            overall = overall and passed
        return overall, outcomes


__all__ = [
    "DECLARED_AGENT_KPIS",
    "KpiCollector",
    "KpiEvidenceState",
    "KpiSample",
    "PromotionGate",
    "PromotionGateThreshold",
]
