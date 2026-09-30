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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    NOT_OBSERVED = "not_observed"
    NOT_CONNECTED = "not_connected"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"


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
        "t2_proposer_recovery_detection_rate",
        "false_positive_rate",
        "missed_critical_rate",
        "stale_inventory_detection_delay_seconds",
        "proposer_exhaustion_to_hil_delay_seconds",
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
    observed_at: str = ""
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
    clock: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(tz=UTC))

    def record(
        self,
        *,
        agent: str,
        metric: str,
        value: float | None,
        evidence_state: KpiEvidenceState | str = KpiEvidenceState.MEASURED,
        tags: dict[str, str] | None = None,
        observed_at: str | None = None,
    ) -> KpiSample:
        resolved_state = KpiEvidenceState(evidence_state)
        sample_tags = dict(tags or {})
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError("KPI value MUST be finite when measured")
        if resolved_state is KpiEvidenceState.MEASURED and value is None:
            raise ValueError("measured KPI MUST carry a value")
        if resolved_state is not KpiEvidenceState.MEASURED and value is not None:
            raise ValueError("unavailable KPI MUST NOT carry a value")
        measured_value = float(value) if value is not None else None
        if resolved_state is KpiEvidenceState.MEASURED:
            if measured_value is None:
                raise ValueError("measured KPI MUST carry a value")
            self._validate_measured_sample(metric=metric, value=measured_value, tags=sample_tags)
        sample = KpiSample(
            agent=agent,
            metric=metric,
            value=measured_value,
            evidence_state=resolved_state,
            observed_at=observed_at or sample_tags.get("observed_at") or self.clock().isoformat(),
            tags=sample_tags,
        )
        self.samples.append(sample)
        self._latest[(agent, metric)] = sample
        return sample

    def report_declared(
        self,
        *,
        agent: str,
        values: Mapping[str, float] | None = None,
        unavailable_state: KpiEvidenceState = KpiEvidenceState.NOT_OBSERVED,
        tags: dict[str, str] | None = None,
        metric_tags: Mapping[str, Mapping[str, str]] | None = None,
        observed_at: str | None = None,
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
                merged_tags = dict(tags or {})
                merged_tags.update(dict((metric_tags or {}).get(metric, {})))
                samples.append(
                    self.record(
                        agent=agent,
                        metric=metric,
                        value=supplied[metric],
                        evidence_state=KpiEvidenceState.MEASURED,
                        tags=merged_tags,
                        observed_at=observed_at,
                    )
                )
                continue
            existing = self.latest(agent=agent, metric=metric)
            if existing is not None and existing.evidence_state is KpiEvidenceState.MEASURED:
                unavailable = KpiEvidenceState.STALE
                unavailable_tags = dict(tags or {})
                unavailable_tags["previous_observed_at"] = existing.observed_at
                unavailable_tags["reason"] = "current_source_missing"
                samples.append(
                    self.record(
                        agent=agent,
                        metric=metric,
                        value=None,
                        evidence_state=unavailable,
                        tags=unavailable_tags,
                        observed_at=observed_at,
                    )
                )
                continue
            samples.append(
                self.record(
                    agent=agent,
                    metric=metric,
                    value=None,
                    evidence_state=unavailable_state,
                    tags=tags,
                    observed_at=observed_at,
                )
            )
        return tuple(samples)

    def _validate_measured_sample(
        self, *, metric: str, value: float, tags: Mapping[str, str]
    ) -> None:
        if _is_unit_interval_metric(metric) and not 0.0 <= value <= 1.0:
            raise ValueError(f"KPI {metric} MUST be in the range [0, 1]")
        if metric.endswith(("_rate", "_ratio")):
            denominator = _positive_int_tag(tags, "denominator")
            if denominator is None:
                raise ValueError(f"KPI {metric} MUST carry a positive denominator tag")
        if metric.endswith("_seconds"):
            if value < 0:
                raise ValueError(f"KPI {metric} MUST NOT be negative")
            if tags.get("unit") != "seconds":
                raise ValueError(f"KPI {metric} MUST carry unit=seconds")
            sample_count = _positive_int_tag(tags, "sample_count")
            if sample_count is None:
                raise ValueError(f"KPI {metric} MUST carry a positive sample_count tag")

    def latest(self, *, agent: str, metric: str) -> KpiSample | None:
        return self._latest.get((agent, metric))

    def all_for(self, agent: str) -> tuple[KpiSample, ...]:
        return tuple(s for s in self.samples if s.agent == agent)

    def coverage(self) -> dict[str, dict[str, int]]:
        return {
            agent: {
                "declared": len(metrics),
                "reported": sum(
                    (sample := self.latest(agent=agent, metric=metric)) is not None
                    and sample.evidence_state is KpiEvidenceState.MEASURED
                    for metric in metrics
                ),
                "current": sum(
                    self.latest(agent=agent, metric=metric) is not None for metric in metrics
                ),
                "measured": sum(
                    (sample := self.latest(agent=agent, metric=metric)) is not None
                    and sample.evidence_state is KpiEvidenceState.MEASURED
                    for metric in metrics
                ),
                "unavailable": sum(
                    (sample := self.latest(agent=agent, metric=metric)) is not None
                    and sample.evidence_state is not KpiEvidenceState.MEASURED
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


def _is_unit_interval_metric(metric: str) -> bool:
    return metric.endswith(("_rate", "_ratio")) or metric.endswith(
        (
            "_accuracy",
            "_precision",
            "_recall",
            "_compliance",
            "_adherence",
        )
    )


def _positive_int_tag(tags: Mapping[str, str], key: str) -> int | None:
    raw = tags.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


__all__ = [
    "DECLARED_AGENT_KPIS",
    "KpiCollector",
    "KpiEvidenceState",
    "KpiSample",
    "PromotionGate",
    "PromotionGateThreshold",
]
