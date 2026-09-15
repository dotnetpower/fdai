"""Supported native metric fields change exactly once without creating a resource."""

import hashlib
import json

import pytest
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.detection.alert_noise.temporal_evaluation import compare_temporal_evaluation
from fdai.delivery.alert_noise_iac import (
    AlertIaCBinding,
    conditional_restore,
    render_alert_iac,
)
from fdai.delivery.alert_noise_metric_iac import patch_metric_evaluation
from fdai_service_contracts.alert_noise import NoisePolicy
from fdai_service_contracts.alert_noise_plan import AlertTreatment

from .test_temporal_evaluation import _cohort, _configs


def _criterion() -> dict:
    return {"threshold": 80.0, "aggregation": "Average", "operator": "GreaterThan"}


@pytest.mark.parametrize("frequency", [False, True])
def test_temporal_iac_retains_exact_rollback_and_unrelated_fields(evidence, now, frequency):
    baseline, candidate = _configs(evidence, frequency=frequency)
    evidence = evidence.model_copy(
        update={"rules": (evidence.rules[0].model_copy(update={"evaluation": baseline}),)}
    )
    receipt = compare_temporal_evaluation(
        _cohort(now, evidence, frequency=frequency), baseline=baseline, treatment=candidate, now=now
    )
    plan = plan_alert_change(
        evidence,
        AlertTreatment(kind="evaluation", target_ref=evidence.rules[0].ref, evaluation=candidate),
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
        evaluation_receipt=receipt,
    )
    resource = {
        "criteria": [_criterion()],
        "window_size": f"PT{baseline.window_seconds // 60}M",
        "frequency": "PT1M",
        "description": "unchanged",
        "action": [{"action_group_id": "group:old"}],
    }
    document = {"resource": {"azurerm_monitor_metric_alert": {"example": resource}}}
    source = json.dumps(document) + "\n"
    binding = AlertIaCBinding(
        path="alerts.tf.json",
        source_digest="sha256:" + hashlib.sha256(source.encode()).hexdigest(),
        resource_type="azurerm_monitor_metric_alert",
        resource_name="example",
        field="frequency" if frequency else "window_size",
        group_ids={},
        target_ref=evidence.rules[0].ref,
    )
    patch = render_alert_iac(plan, evidence, binding=binding, source=source)
    changed = json.loads(patch.forward)["resource"][binding.resource_type][binding.resource_name]
    assert changed == {**resource, binding.field: "PT5M"}
    assert conditional_restore(patch, current=patch.forward) == source
    with pytest.raises(ValueError, match="newer"):
        conditional_restore(patch, current=patch.forward + " ")


@pytest.mark.parametrize("field", ["frequency", "window_size", "criteria.0.threshold", "action"])
def test_wrong_axis_mapping_never_patches(evidence, field):
    baseline, treatment = _configs(evidence)
    if field == "window_size":
        treatment = baseline.model_copy(update={"frequency_seconds": 300})
    resource = {"criteria": [{"threshold": 80.0}], "window_size": "PT1M", "frequency": "PT1M"}
    before = json.dumps(resource)
    with pytest.raises(ValueError, match="mapping"):
        patch_metric_evaluation(resource, baseline, treatment, field=field)
    assert json.dumps(resource) == before


@pytest.mark.parametrize(
    "change",
    [
        {"criteria": []},
        {"criteria": [{"threshold": 80.0}, {"threshold": 80.0}]},
        {"criteria": [False]},
        {"criteria": [{"threshold": True}]},
        {"criteria": [{"threshold": 81.0}]},
        {"criteria": [{"threshold": "80"}]},
        {"dynamic_criteria": [{}]},
        {"application_insights_web_test_location_availability_criteria": [{}]},
        {"window_size": "${var.window}"},
        {"window_size": "PT"},
        {"window_size": 60},
        {"frequency": "PT5M"},
        {"window_size": "PT2M"},
    ],
)
def test_unknown_or_mismatched_native_config_never_changes(evidence, change):
    baseline, treatment = _configs(evidence)
    resource = {
        "criteria": [_criterion()],
        "window_size": "PT1M",
        "frequency": "PT1M",
        **change,
    }
    before = json.dumps(resource)
    with pytest.raises(ValueError):
        patch_metric_evaluation(resource, baseline, treatment, field="window_size")
    assert json.dumps(resource) == before


@pytest.mark.parametrize(
    "axis,seconds",
    [("window_seconds", 600), ("frequency_seconds", 120), ("frequency_seconds", 300)],
)
def test_unsupported_native_treatment_holds(evidence, axis, seconds):
    baseline, _ = _configs(evidence)
    resource = {"criteria": [_criterion()], "window_size": "PT1M", "frequency": "PT1M"}
    with pytest.raises(ValueError, match="duration"):
        patch_metric_evaluation(
            resource,
            baseline,
            baseline.model_copy(update={axis: seconds}),
            field="window_size" if axis == "window_seconds" else "frequency",
        )


def test_threshold_retains_existing_mapping(evidence):
    baseline, _ = _configs(evidence)
    resource = {"criteria": [{"threshold": 80.0}], "description": "unchanged"}
    patch_metric_evaluation(
        resource,
        baseline,
        baseline.model_copy(update={"threshold": 90.0}),
        field="criteria.0.threshold",
    )
    assert resource == {"criteria": [{"threshold": 90.0}], "description": "unchanged"}


@pytest.mark.parametrize(
    "seconds,native", [(3600, "PT1H"), (21600, "PT6H"), (43200, "PT12H"), (86400, "P1D")]
)
def test_renderer_uses_provider_accepted_hour_and_day_durations(evidence, seconds, native):
    baseline, _ = _configs(evidence)
    resource = {"criteria": [_criterion()], "window_size": "PT1M", "frequency": "PT1M"}
    patch_metric_evaluation(
        resource,
        baseline,
        baseline.model_copy(update={"window_seconds": seconds}),
        field="window_size",
    )
    assert resource["window_size"] == native


@pytest.mark.parametrize(
    "change", [{"aggregation": "Maximum"}, {"operator": "LessThan"}, {"dimension": [{}]}]
)
def test_temporal_iac_rechecks_full_native_criterion(evidence, change):
    baseline, treatment = _configs(evidence)
    resource = {
        "criteria": [{**_criterion(), **change}],
        "window_size": "PT1M",
        "frequency": "PT1M",
    }
    with pytest.raises(ValueError, match="simple semantics"):
        patch_metric_evaluation(resource, baseline, treatment, field="window_size")
