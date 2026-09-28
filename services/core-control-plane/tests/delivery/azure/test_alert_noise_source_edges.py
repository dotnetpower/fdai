"""Additional Azure alert source fail-closed edge coverage."""

from __future__ import annotations

import pytest
from fdai.delivery.azure.alert_noise_source import AlertScopeBinding

from tests.delivery.azure.test_alert_noise_source import (
    GROUP,
    NOW,
    SUB_ID,
    collect,
    group,
    metric,
    processing,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"subscription_id": "bad/sub"},
        {"resource_group": "example-rg."},
        {"tenant_ref": "Tenant:Example"},
        {"scope_ref": "scope/example"},
        {"pseudonym_key": b"too-short"},
        {"policy_bindings": []},
        {"policy_bindings": {1: {}}},
        {"policy_bindings": {"rule": []}},
    ],
)
def test_scope_binding_rejects_untrusted_native_scope_or_policy(changes: dict[str, object]) -> None:
    values = {
        "subscription_id": SUB_ID,
        "resource_group": "example-rg",
        "tenant_ref": "tenant:example",
        "scope_ref": "scope:example",
        "pseudonym_key": b"synthetic-key-" * 3,
        "policy_bindings": {},
    }
    values.update(changes)
    with pytest.raises(ValueError):
        AlertScopeBinding(**values)


async def test_pseudonym_and_cutoff_inputs_fail_closed_before_collection() -> None:
    _, _, source = await collect()
    for kind, value in [("Rule", "x"), ("bad_kind", "x"), ("rule", 1)]:
        with pytest.raises(ValueError, match="pseudonym input"):
            source.opaque(kind, value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        await source.collect_period(now=NOW.replace(tzinfo=None), period_seconds=3600)


async def test_duplicate_and_malformed_native_rows_lower_coverage_without_empty_success() -> None:
    duplicate_rule = metric()
    duplicate_group = group()
    duplicate_group["properties"]["emailReceivers"].append(
        {"name": "example-email", "emailAddress": "other@example.com"}
    )
    malformed_receiver = group(GROUP + "-malformed")
    malformed_receiver["properties"]["emailReceivers"] = [True]
    duplicate_processing = processing()

    evidence, _, _ = await collect(
        {
            "metricAlerts": [metric(), duplicate_rule],
            "actionGroups": [duplicate_group, malformed_receiver],
            "actionRules": [processing(), duplicate_processing],
        }
    )

    assert evidence.rules == ()
    assert evidence.groups == ()
    assert evidence.processing_rules == ()
    assert {
        "rule_shape_or_scope_incomplete",
        "group_shape_or_scope_incomplete",
        "processing_semantics_unknown",
    }.issubset(evidence.stamp.reasons)
    assert evidence.stamp.coverage == "partial"


async def test_unknown_receiver_kinds_are_automation_not_audience_membership() -> None:
    raw = group()
    raw["properties"]["webhookReceivers"] = [
        {"name": "example-webhook", "serviceUri": "https://example.com/hook"}
    ]

    evidence, _, _ = await collect({"actionGroups": [raw]})

    assert len(evidence.groups) == 1
    assert evidence.groups[0].automation_refs
    assert evidence.audiences[0].kind == "direct"
    assert "automation_semantics_unverified" in evidence.stamp.reasons


async def test_other_subscription_resources_are_not_accepted_as_bound_scope() -> None:
    raw = metric()
    raw["id"] = raw["id"].replace(SUB_ID, "00000000-0000-0000-0000-000000000001")

    evidence, _, _ = await collect({"metricAlerts": [raw]})

    assert evidence.rules == ()
    assert "rule_shape_or_scope_incomplete" in evidence.stamp.reasons
