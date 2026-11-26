"""Patch only one observed simple Azure metric evaluation field in existing Terraform JSON."""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.alert_noise import Evaluation
from fdai_service_contracts.alert_noise_evaluation import evaluation_axis

_DURATIONS = {
    60: "PT1M",
    300: "PT5M",
    900: "PT15M",
    1800: "PT30M",
    3600: "PT1H",
    21600: "PT6H",
    43200: "PT12H",
    86400: "P1D",
}
_WINDOWS = frozenset(_DURATIONS)
_FREQUENCIES = frozenset({60, 300, 900, 1800, 3600})


def _seconds(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    return next((seconds for seconds, native in _DURATIONS.items() if native == value), None)


def patch_metric_evaluation(
    resource: dict[str, Any], baseline: Evaluation, treatment: Evaluation, *, field: str
) -> None:
    """Validate exact field binding; preserve other settings and hold unsupported shapes."""
    axis = evaluation_axis(baseline, treatment)
    expected = {
        "threshold": "criteria.0.threshold",
        "window_seconds": "window_size",
        "frequency_seconds": "frequency",
    }
    if axis is None or field != expected[axis]:
        raise ValueError("alert IaC evaluation mapping is unsupported")
    criteria = resource.get("criteria")
    if not isinstance(criteria, list) or len(criteria) != 1 or not isinstance(criteria[0], dict):
        raise ValueError("alert IaC requires one simple metric criterion")
    if resource.get("dynamic_criteria") or resource.get(
        "application_insights_web_test_location_availability_criteria"
    ):
        raise ValueError("alert IaC mixed metric criteria are unsupported")
    if type(criteria[0].get("threshold")) not in {int, float} or (
        criteria[0]["threshold"] != baseline.threshold
    ):
        raise ValueError("alert IaC threshold differs from observed baseline")
    if axis == "threshold":
        criteria[0]["threshold"] = treatment.threshold
        return
    if (
        criteria[0].get("aggregation") != baseline.aggregation.capitalize()
        or criteria[0].get("operator")
        != {"above": "GreaterThan", "below": "LessThan"}[baseline.operator]
        or criteria[0].get("dimension")
    ):
        raise ValueError("alert IaC temporal criterion differs from observed simple semantics")
    if (
        _seconds(resource.get("window_size")) != baseline.window_seconds
        or _seconds(resource.get("frequency")) != baseline.frequency_seconds
        or treatment.window_seconds not in _WINDOWS
        or treatment.frequency_seconds not in _FREQUENCIES
        or treatment.frequency_seconds > treatment.window_seconds
    ):
        raise ValueError("alert IaC metric duration differs from observed or supported semantics")
    seconds = getattr(treatment, axis)
    resource[field] = _DURATIONS[seconds]
