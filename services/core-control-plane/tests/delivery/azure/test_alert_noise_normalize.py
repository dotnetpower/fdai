"""Deterministic native-wire fixtures for narrow metric and processing-rule semantics."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.delivery.azure.alert_noise_normalize import (
    metric_evaluation,
    native_resource,
    native_scope,
    notification_kind,
    processing_rule,
    rule_groups,
)

SUB = "/subscriptions/00000000-0000-0000-0000-000000000000"
RG = SUB + "/resourceGroups/example-rg"
TARGET = RG + "/providers/Microsoft.Compute/virtualMachines/example-vm"
RULE = RG + "/providers/Microsoft.Insights/metricAlerts/example-rule"
GROUP = RG + "/providers/Microsoft.Insights/actionGroups/example-group"
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def opaque(kind: str, value: str) -> str:
    # Synthetic test-only identifiers. Production pseudonyms require a deployment key.
    return kind + ":" + hashlib.sha256(value.casefold().encode()).hexdigest()


def metric() -> dict[str, Any]:
    return {
        "scopes": [TARGET],
        "evaluationFrequency": "PT1M",
        "windowSize": "PT5M",
        "criteria": {
            "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            "allOf": [
                {
                    "name": "cpu",
                    "criterionType": "StaticThresholdCriterion",
                    "metricName": "Percentage CPU",
                    "metricNamespace": "Microsoft.Compute/virtualMachines",
                    "dimensions": [],
                    "operator": "GreaterThan",
                    "threshold": 80,
                    "timeAggregation": "Average",
                }
            ],
        },
    }


def processing(action: str = "RemoveAllActionGroups") -> dict[str, Any]:
    action_row: dict[str, Any] = {"actionType": action}
    if action == "AddActionGroups":
        action_row["actionGroupIds"] = [GROUP]
    return {
        "id": RG + "/providers/Microsoft.AlertsManagement/actionRules/example-window",
        "type": "Microsoft.AlertsManagement/actionRules",
        "properties": {
            "scopes": [RG],
            "enabled": True,
            "conditions": [{"field": "AlertRuleId", "operator": "Equals", "values": [RULE]}],
            "schedule": {
                "timeZone": "UTC",
                "effectiveFrom": "2026-09-14T11:00:00",
                "effectiveUntil": "2026-09-14T13:00:00",
            },
            "actions": [action_row],
        },
    }


def decode(raw: dict[str, Any], **overrides: Any) -> Any:
    options = {
        "native_rules": {RULE.casefold(): "rule:observed"},
        "native_targets": {RULE.casefold(): (TARGET.casefold(),)},
        "native_groups": {GROUP.casefold(): "group:observed"},
        "authorized_scope": RG.casefold(),
        "opaque": opaque,
        "revision": DIGEST,
        "now": NOW,
    }
    options.update(overrides)
    return processing_rule(raw, **options)


def test_single_static_metric_preserves_numeric_threshold_and_resource_scope() -> None:
    result = metric_evaluation(metric(), opaque)
    assert result is not None
    assert result.threshold == 80.0
    assert (result.window_seconds, result.frequency_seconds) == (300, 60)
    assert (result.operator, result.aggregation) == ("above", "average")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("threshold", "80"),
        ("threshold", True),
        ("threshold", float("inf")),
        ("threshold", float("nan")),
        ("threshold", 9007199254740993),
        ("operator", ["GreaterThan"]),
        ("timeAggregation", {}),
        ("metricNamespace", []),
        ("metricName", 12),
        ("dimensions", {}),
        ("dimensions", [{"name": "region", "values": ["example"]}]),
        ("criterionType", "DynamicThresholdCriterion"),
        ("operator", "GreaterThanOrEqual"),
        ("timeAggregation", "Total"),
        ("skipMetricValidation", "false"),
        ("unknownSemantics", True),
    ],
)
def test_metric_never_coerces_malformed_or_unsupported_criterion(
    field: str,
    value: object,
) -> None:
    raw = metric()
    raw["criteria"]["allOf"][0][field] = value
    assert metric_evaluation(raw, opaque) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scopes", [RG]),
        ("scopes", []),
        ("scopes", [TARGET, TARGET + "2"]),
        ("scopes", TARGET),
        ("windowSize", "PT2M"),
        ("evaluationFrequency", "PT15M"),
    ],
)
def test_metric_requires_one_actual_target_and_supported_durations(
    field: str,
    value: object,
) -> None:
    raw = metric()
    raw[field] = value
    assert metric_evaluation(raw, opaque) is None


def test_metric_requires_exact_criteria_discriminator_and_one_criterion() -> None:
    raw = metric()
    raw["criteria"].pop("odata.type")
    assert metric_evaluation(raw, opaque) is None
    raw = metric()
    raw["criteria"]["allOf"].append(deepcopy(raw["criteria"]["allOf"][0]))
    assert metric_evaluation(raw, opaque) is None


def test_native_rule_action_shapes_are_distinct() -> None:
    metric_refs = rule_groups({"actions": [{"actionGroupId": GROUP}]}, "metric")
    log_refs = rule_groups({"actions": {"actionGroups": [GROUP]}}, "log")
    activity_refs = rule_groups(
        {"actions": {"actionGroups": [{"actionGroupId": GROUP}]}},
        "activity",
    )
    assert metric_refs == log_refs == activity_refs == (GROUP.casefold(),)
    for properties, kind in [
        ({"actions": {"actionGroups": GROUP}}, "log"),
        ({"actions": {"actionGroups": [GROUP]}}, "activity"),
        ({"actions": [{"actionGroupId": True}]}, "metric"),
        ({}, "activity"),
    ]:
        with pytest.raises(ValueError):
            rule_groups(properties, kind)


def test_suppression_removes_all_groups_with_native_absolute_utc_schedule() -> None:
    result = decode(processing())
    assert result is not None and result.semantics_complete
    assert result.action == "suppress" and result.group_refs == ()
    assert result.rule_refs == ("rule:observed",)
    assert result.effective_from == datetime(2026, 9, 14, 11, tzinfo=UTC)
    assert result.effective_to == datetime(2026, 9, 14, 13, tzinfo=UTC)


def test_additions_require_observed_real_action_groups() -> None:
    result = decode(processing("AddActionGroups"))
    assert result is not None and result.semantics_complete
    assert result.action == "add" and result.group_refs == ("group:observed",)
    missing = decode(processing("AddActionGroups"), native_groups={})
    assert missing is not None and not missing.semantics_complete and missing.group_refs == ()


@pytest.mark.parametrize("scope", [SUB, SUB + "/resourceGroups/example-rg-other", RULE])
def test_processing_scope_is_monitored_resource_scope_not_rule_storage(scope: str) -> None:
    raw = processing()
    raw["properties"]["scopes"] = [scope]
    result = decode(raw)
    assert result is not None and not result.semantics_complete


def test_exact_target_scope_and_resource_group_casing_are_supported() -> None:
    raw = processing()
    raw["properties"]["scopes"] = [TARGET.upper()]
    result = decode(raw, authorized_scope=RG.upper())
    assert result is not None and result.semantics_complete


@pytest.mark.parametrize(
    "conditions",
    [
        [],
        [{"field": "AlertRuleName", "operator": "Equals", "values": ["example-rule"]}],
        [{"field": "AlertRuleId", "operator": "Contains", "values": [RULE]}],
        [{"field": "AlertRuleId", "operator": "Equals", "values": [RULE, RULE]}],
        [{"field": "AlertRuleId", "operator": "Equals", "values": [RULE + "-unseen"]}],
        [{"field": "AlertRuleId", "operator": "Equals", "values": [RULE], "unknown": True}],
        [
            {"field": "AlertRuleId", "operator": "Equals", "values": [RULE]},
            {"field": "Severity", "operator": "Equals", "values": ["Sev3"]},
        ],
    ],
)
def test_only_one_exact_rule_id_filter_can_be_complete(conditions: object) -> None:
    raw = processing()
    raw["properties"]["conditions"] = conditions
    result = decode(raw)
    assert result is not None and not result.semantics_complete


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conditions", {"alertRuleId": {"operator": "Equals", "values": [RULE]}}),
        ("conditions", [{"field": "AlertRuleId", "operator": "Equals", "values": RULE}]),
        ("conditions", [{"field": "AlertRuleId", "operator": {}, "values": [RULE]}]),
        ("conditions", [{"field": "AlertRuleId", "operator": "Equals", "values": [True]}]),
        ("scopes", RG),
        ("scopes", [True]),
        ("enabled", "false"),
        ("actions", {}),
        ("actions", [True]),
        ("schedule", "UTC"),
    ],
)
def test_processing_rejects_non_native_types(field: str, value: object) -> None:
    raw = processing()
    raw["properties"][field] = value
    with pytest.raises(ValueError):
        decode(raw)


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-14T11:00:00Z",
        "2026-09-14T11:00:00+00:00",
        "2026-09-14",
        "2026-09-14T11:00:00-04:00",
        "2026-09-14T11:00:00.1234567",
        True,
    ],
)
def test_processing_requires_swagger_suffix_free_schedule_times(value: object) -> None:
    raw = processing()
    raw["properties"]["schedule"]["effectiveFrom"] = value
    with pytest.raises(ValueError):
        decode(raw)


def test_unknown_actions_or_schedules_never_get_invented_intervals() -> None:
    raw = processing("FutureAction")
    assert decode(raw) is None
    raw = processing()
    raw["properties"].pop("schedule")
    assert decode(raw) is None
    raw = processing()
    raw["properties"]["schedule"].pop("effectiveUntil")
    assert decode(raw) is None
    raw = processing()
    raw["properties"]["schedule"]["timeZone"] = "Pacific Standard Time"
    assert decode(raw) is None
    raw = processing()
    raw["properties"]["actions"][0]["actionGroupIds"] = [GROUP]
    assert decode(raw) is None


def test_recurrence_and_missing_target_evidence_are_never_complete() -> None:
    raw = processing()
    raw["properties"]["schedule"]["recurrences"] = [{"recurrenceType": "Daily"}]
    result = decode(raw)
    assert result is not None and not result.semantics_complete
    result = decode(processing(), native_targets={})
    assert result is not None and not result.semantics_complete and result.rule_refs == ()
    result = decode(processing(), authorized_scope=None)
    assert result is not None and not result.semantics_complete


@pytest.mark.parametrize("role_id", [True, {}, [], "Owner", GROUP, ""])
def test_arm_role_receiver_rejects_fake_or_stringified_identifiers(role_id: object) -> None:
    with pytest.raises(ValueError):
        notification_kind("armRoleReceivers", {"name": "example-role", "roleId": role_id})


def test_role_receiver_records_mechanism_only_and_does_not_expand_permissions() -> None:
    receiver = {"name": "example-role", "roleId": "00000000-0000-0000-0000-000000000000"}
    assert notification_kind("armRoleReceivers", receiver) == "role"
    receiver["useCommonAlertSchema"] = "true"
    with pytest.raises(ValueError):
        notification_kind("armRoleReceivers", receiver)


@pytest.mark.parametrize(
    "scope",
    [
        RG + "/../example-rg",
        RG + "%2fproviders/example/type/name",
        "https://example.com/",
        RG + "?query=value",
        RG + "/providers/Microsoft.Compute/virtualMachines/*",
        123,
    ],
)
def test_native_scopes_are_not_urls_or_arbitrary_strings(scope: object) -> None:
    with pytest.raises(ValueError):
        native_scope(scope)


def test_native_type_must_match_resource_id() -> None:
    raw = processing()
    raw["type"] = "Microsoft.Insights/metricAlerts"
    with pytest.raises(ValueError):
        native_resource(raw, "Microsoft.AlertsManagement/actionRules")
