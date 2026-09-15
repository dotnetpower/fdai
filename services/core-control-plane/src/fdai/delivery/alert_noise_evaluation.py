"""Replay independently admitted frozen inputs, or decode an independently reviewed comparison."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.alert_noise import AlertRule
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationReceipt,
    EvaluationScenarioSet,
    TemporalEvaluationScenarioSet,
)
from fdai_service_contracts.alert_noise_plan import AlertTreatment

from fdai.core.detection.alert_noise.evaluation import compare_evaluation
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.temporal_evaluation import compare_temporal_evaluation
from fdai.delivery.alert_noise_records import exact_alert_model


def admitted_alert_comparison(
    payload: Mapping[str, Any],
    *,
    rule: AlertRule,
    treatment: AlertTreatment,
    verified_at: datetime,
) -> EvaluationReceipt:
    """Consume exact admitted input without creating labels, authority or live-provider evidence.

    The enclosing reader authenticates the complete payload's scope, purpose, source and
    revision first. Replay time is the immutable admission time, so retries do not renew it.
    Only one source shape is accepted; callers still check freshness and exact rule binding.
    """
    fields = set(payload) - {"evidence_digest", "treatment_digest"}
    if fields == {"comparison"}:
        return exact_alert_model(EvaluationReceipt, payload["comparison"])
    if rule.evaluation is None or treatment.evaluation is None:
        raise AlertExecutionHeld("alert_evaluation_kind_unsupported")
    try:
        if fields == {"threshold_scenarios"}:
            buckets = exact_alert_model(EvaluationScenarioSet, payload["threshold_scenarios"])
            return compare_evaluation(
                buckets, baseline=rule.evaluation, treatment=treatment.evaluation, now=verified_at
            )
        if fields == {"temporal_scenarios"} and rule.kind == "metric":
            series = exact_alert_model(TemporalEvaluationScenarioSet, payload["temporal_scenarios"])
            return compare_temporal_evaluation(
                series, baseline=rule.evaluation, treatment=treatment.evaluation, now=verified_at
            )
    except (ValueError, ArithmeticError):
        raise AlertExecutionHeld("alert_evaluation_scenarios_unscorable") from None
    raise AlertExecutionHeld("alert_evaluation_binding_mismatch")
