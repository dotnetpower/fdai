"""Synthetic no-network collection fixtures; no notification, directory or Azure side effects."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.delivery.azure.alert_noise_http import AZURE_ALERT_APIS, AlertReadLimits, AzureAlertReader
from fdai.delivery.azure.alert_noise_source import AlertScopeBinding, AzureAlertEvidenceSource
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.alert_noise import AlertEvidence, Audience

SUB_ID = "00000000-0000-0000-0000-000000000000"
SUB = "/subscriptions/" + SUB_ID
RG = SUB + "/resourceGroups/example-rg"
TARGET = RG + "/providers/Microsoft.Compute/virtualMachines/example-vm"
RULE = RG + "/providers/Microsoft.Insights/metricAlerts/example-rule"
GROUP = RG + "/providers/Microsoft.Insights/actionGroups/example-group"
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
VERSION = "sha256:" + "a" * 64
_DEFAULT_READ_LIMITS = AlertReadLimits()


class Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        assert audience == "https://management.azure.com/.default"
        return IdentityToken("synthetic-token", NOW + timedelta(minutes=5), audience)


def metric() -> dict[str, Any]:
    return {
        "id": RULE,
        "type": "Microsoft.Insights/metricAlerts",
        "name": "example-rule",
        "properties": {
            "enabled": True,
            "severity": 3,
            "scopes": [TARGET],
            "autoMitigate": False,
            "evaluationFrequency": "PT1M",
            "windowSize": "PT5M",
            "actions": [{"actionGroupId": GROUP}],
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
        },
    }


def group(native: str = GROUP) -> dict[str, Any]:
    return {
        "id": native,
        "type": "Microsoft.Insights/actionGroups",
        "properties": {
            "groupShortName": "example",
            "enabled": True,
            "emailReceivers": [{"name": "example-email", "emailAddress": "user@example.com"}],
        },
    }


def processing() -> dict[str, Any]:
    return {
        "id": RG + "/providers/Microsoft.AlertsManagement/actionRules/example-window",
        "type": "Microsoft.AlertsManagement/actionRules",
        "properties": {
            "enabled": True,
            "scopes": [RG],
            "conditions": [{"field": "AlertRuleId", "operator": "Equals", "values": [RULE]}],
            "schedule": {
                "timeZone": "UTC",
                "effectiveFrom": "2026-09-14T11:00:00",
                "effectiveUntil": "2026-09-14T13:00:00",
            },
            "actions": [{"actionType": "AddActionGroups", "actionGroupIds": [GROUP]}],
        },
    }


class Resolver:
    def __init__(
        self,
        *,
        coverage: str = "complete",
        wrong_ref: bool = False,
        raise_error: bool = False,
        member_ref: str = "principal:" + "b" * 64,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.coverage, self.wrong_ref, self.raise_error = coverage, wrong_ref, raise_error
        self.member_ref = member_ref

    async def resolve(self, *, binding_ref: str, kind: str, private_value: str) -> Audience:
        self.calls.append(json.loads(private_value))
        if self.raise_error:
            raise RuntimeError("private-provider-message user@example.com")
        return Audience.model_validate(
            {
                "ref": "audience:wrong" if self.wrong_ref else binding_ref,
                "kind": kind,
                "member_refs": (self.member_ref,),
                "potential_members": 1 if self.coverage == "complete" else 2,
                "coverage": self.coverage,
                "revision": VERSION,
                "primary_verified": self.coverage == "complete",
                "backup_verified": False,
            }
        )


async def collect(
    rows: dict[str, list[dict[str, Any]]] | None = None,
    *,
    statuses: dict[str, int] | None = None,
    resolver: Resolver | None = None,
    policy: dict[str, Any] | None = None,
    limits: AlertReadLimits = _DEFAULT_READ_LIMITS,
    scope_ref: str = "scope:example",
    period_seconds: int | None = None,
) -> tuple[AlertEvidence, list[httpx.Request], AzureAlertEvidenceSource]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.host == "management.azure.com"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        family = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            (statuses or {}).get(family, 200), json={"value": (rows or {}).get(family, [])}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = AzureAlertEvidenceSource(
            reader=AzureAlertReader(
                http=client,
                identity=Identity(),
                clock=lambda: NOW,
                limits=limits,
            ),
            binding=AlertScopeBinding(
                subscription_id=SUB_ID,
                resource_group="example-rg",
                tenant_ref="tenant:example",
                scope_ref=scope_ref,
                pseudonym_key=b"synthetic-key-" * 3,
                policy_bindings=policy or {},
            ),
            audiences=resolver,
        )
        evidence = (
            await source.collect(now=NOW)
            if period_seconds is None
            else await source.collect_period(now=NOW, period_seconds=period_seconds)
        )
        return evidence, requests, source


@pytest.mark.parametrize("seconds", [3600, 86400, 604800])
async def test_selected_period_is_the_actual_bounded_native_history_query(seconds):
    evidence, requests, _ = await collect(period_seconds=seconds)
    start = NOW - timedelta(seconds=seconds)
    assert evidence.window_start == start and evidence.window_end == NOW
    assert requests[-1].url.params["customTimeRange"] == f"{start.isoformat()}/{NOW.isoformat()}"
    assert evidence.stamp.coverage == "partial"
    assert all(request.method == "GET" for request in requests)


async def test_collection_uses_pinned_gets_and_actual_rg_history_scope() -> None:
    evidence, requests, _ = await collect()
    assert len(requests) == 6
    for request, (collection, version) in zip(requests, AZURE_ALERT_APIS.items(), strict=True):
        assert request.url.params["api-version"] == version
        assert request.url.path.endswith("/providers/" + collection)
    history = requests[-1]
    expected_path = RG + "/providers/Microsoft.AlertsManagement/alerts"
    assert history.url.path.casefold() == expected_path.casefold()
    assert history.url.params["customTimeRange"] == (
        "2026-09-13T12:00:00+00:00/2026-09-14T12:00:00+00:00"
    )
    assert "timeRange" not in history.url.params
    assert history.url.params["includeContext"] == "false"
    assert history.url.params["includeEgressConfig"] == "false"
    assert evidence.history_coverage == "complete" and evidence.delivery_coverage == "unavailable"
    assert evidence.stamp.coverage == "partial"  # Not a complete global source-type inventory.
    assert not evidence.execution_authority and not evidence.independent_collection


async def test_metric_target_and_unbound_replacement_are_observed_without_authority() -> None:
    replacement = GROUP + "-replacement"
    policy = {
        RULE.casefold(): {
            "ownership_verified": True,
            "iac_owned": True,
            "active_incident": False,
            "classification": "informational",
            "service_ref": "service:pretend-owner",
        }
    }
    evidence, _, source = await collect(
        {"metricAlerts": [metric()], "actionGroups": [group(), group(replacement)]}, policy=policy
    )
    rule = evidence.rules[0]
    assert rule.resource_ref == source.opaque("resource", TARGET)
    assert rule.evaluation is not None and rule.evaluation.threshold == 80.0
    assert not rule.stateful and not rule.ownership_verified and not rule.iac_owned
    assert rule.service_ref == "service:unknown" and rule.classification == "unknown"
    assert rule.active_incident and rule.protected
    assert "static_policy_not_observed_authority" in evidence.stamp.reasons
    assert {item.ref for item in evidence.groups} == {
        source.opaque("group", GROUP),
        source.opaque("group", replacement),
    }
    assert all(
        item.coverage == "unavailable"
        and item.potential_members is None
        and not item.primary_verified
        and not item.backup_verified
        for item in evidence.audiences
    )
    serialized = evidence.model_dump_json()
    assert "user@example.com" not in serialized and SUB_ID not in serialized
    assert "example-rule" not in serialized and "Percentage CPU" not in serialized


async def test_activity_log_reverse_edges_are_protected_and_outside_dependents_hold() -> None:
    activity = {
        "id": RG + "/providers/Microsoft.Insights/activityLogAlerts/example-health",
        "type": "Microsoft.Insights/activityLogAlerts",
        "properties": {
            "enabled": True,
            "scopes": [SUB.lstrip("/")],
            "condition": {"allOf": [{"field": "category", "equals": "ServiceHealth"}]},
            "actions": {"actionGroups": [{"actionGroupId": GROUP}]},
        },
    }
    outside = deepcopy(activity)
    outside["id"] = activity["id"].replace("example-rg", "example-rg-other")
    log = {
        "id": RG + "/providers/Microsoft.Insights/scheduledQueryRules/example-log",
        "type": "Microsoft.Insights/scheduledQueryRules",
        "kind": "LogAlert",
        "properties": {
            "enabled": True,
            "severity": 3,
            "scopes": [TARGET],
            "criteria": {"allOf": []},
            "actions": {"actionGroups": [GROUP]},
        },
    }
    evidence, _, source = await collect(
        {
            "metricAlerts": [metric()],
            "actionGroups": [group()],
            "activityLogAlerts": [activity, outside],
            "scheduledQueryRules": [log],
        }
    )
    assert len(evidence.rules) == 3
    health = next(item for item in evidence.rules if item.kind == "activity")
    assert health.protected and health.severity is None
    assert source.opaque("rule", outside["id"]) in evidence.groups[0].rule_refs
    assert set(evidence.groups[0].rule_refs).issuperset(item.ref for item in evidence.rules)
    assert not evidence.groups[0].reverse_complete
    assert "dependencies_outside_scope" in evidence.stamp.reasons


async def test_processing_additions_include_real_unbound_group_and_dependency() -> None:
    replacement = GROUP + "-replacement"
    addition = processing()
    addition["properties"]["actions"][0]["actionGroupIds"] = [replacement]
    evidence, _, source = await collect(
        {
            "metricAlerts": [metric()],
            "actionGroups": [group(), group(replacement)],
            "actionRules": [addition],
        }
    )
    replacement_ref = source.opaque("group", replacement)
    observed = next(item for item in evidence.groups if item.ref == replacement_ref)
    assert evidence.processing_rules[0].semantics_complete
    assert evidence.processing_rules[0].group_refs == (observed.ref,)
    assert evidence.rules[0].ref in observed.rule_refs


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", "false"),
        ("severity", "3"),
        ("severity", True),
        ("autoMitigate", 1),
        ("scopes", [False]),
        ("actions", "[]"),
    ],
)
async def test_malformed_native_rule_fields_do_not_get_coerced(field: str, value: object) -> None:
    raw = metric()
    raw["properties"][field] = value
    evidence, _, _ = await collect({"metricAlerts": [raw]})
    assert evidence.rules == () and "rule_shape_or_scope_incomplete" in evidence.stamp.reasons


async def test_multi_target_does_not_manufacture_rule_id_as_monitored_resource() -> None:
    raw = metric()
    raw["properties"]["scopes"] = [TARGET, TARGET + "-other"]
    evidence, _, _ = await collect({"metricAlerts": [raw]})
    assert evidence.rules[0].resource_ref == "resource:unknown"
    assert evidence.rules[0].evaluation is None


@pytest.mark.parametrize("coverage", ["complete", "partial"])
async def test_only_injected_resolver_can_supply_membership(coverage: str) -> None:
    resolver = Resolver(coverage=coverage)
    raw = group()
    raw["properties"]["armRoleReceivers"] = [{"name": "example-role", "roleId": SUB_ID}]
    evidence, _, _ = await collect({"actionGroups": [raw]}, resolver=resolver)
    assert len(resolver.calls) == 2
    assert all(
        call["tenant_ref"] == "tenant:example"
        and call["scope_ref"] == "scope:example"
        and call["subscription_scope"] == SUB
        for call in resolver.calls
    )
    assert {item.kind for item in evidence.audiences} == {"role", "direct"}
    assert all(item.coverage == coverage for item in evidence.audiences)
    assert all(not item.backup_verified for item in evidence.audiences)
    assert "user@example.com" not in evidence.model_dump_json()


@pytest.mark.parametrize("broken", ["wrong_ref", "raise_error"])
async def test_resolver_failure_keeps_unknown_and_stops_expansion(broken: str) -> None:
    resolver = Resolver(**{broken: True})
    evidence, _, _ = await collect(
        {"actionGroups": [group(), group(GROUP + "-other")]},
        resolver=resolver,
    )
    assert len(resolver.calls) == 1
    assert all(item.coverage == "unavailable" for item in evidence.audiences)
    assert "audience_resolution_failed" in evidence.stamp.reasons
    assert "private-provider-message" not in evidence.model_dump_json()


async def test_resolver_cannot_publish_enumerable_identity_or_expand_without_budget() -> None:
    evidence, _, _ = await collect(
        {"actionGroups": [group()]}, resolver=Resolver(member_ref="principal:alice")
    )
    assert evidence.audiences[0].coverage == "unavailable"
    resolver = Resolver()
    evidence, _, _ = await collect(
        {"actionGroups": [group(), group(GROUP + "-other")]},
        resolver=resolver,
        limits=AlertReadLimits(total_pages=7),
    )
    assert len(resolver.calls) == 1
    assert {item.coverage for item in evidence.audiences} == {"complete", "unavailable"}


async def test_audience_revision_pins_native_binding_as_well_as_resolver_result() -> None:
    first, _, _ = await collect({"actionGroups": [group()]}, resolver=Resolver())
    changed = group()
    changed["properties"]["emailReceivers"][0]["emailAddress"] = "other@example.com"
    second, _, _ = await collect({"actionGroups": [changed]}, resolver=Resolver())
    assert first.audiences[0].ref == second.audiences[0].ref
    assert first.audiences[0].revision != second.audiences[0].revision


async def test_disabled_or_outside_groups_cannot_expand_receivers() -> None:
    resolver = Resolver()
    disabled = group()
    disabled["properties"]["enabled"] = False
    outside_id = GROUP.replace("example-rg", "example-rg-other")
    rule = metric()
    rule["properties"]["actions"].append({"actionGroupId": outside_id})
    evidence, _, _ = await collect(
        {"metricAlerts": [rule], "actionGroups": [disabled, group(outside_id)]}, resolver=resolver
    )
    assert resolver.calls == [] and len(evidence.groups) == 2
    assert all(item.coverage == "unavailable" for item in evidence.audiences)


async def test_native_role_and_receiver_arrays_are_strict() -> None:
    raw = group()
    raw["properties"]["armRoleReceivers"] = [{"name": "role", "roleId": [SUB_ID]}]
    resolver = Resolver()
    evidence, _, _ = await collect({"actionGroups": [raw]}, resolver=resolver)
    assert evidence.groups == () and resolver.calls == []
    assert "group_shape_or_scope_incomplete" in evidence.stamp.reasons


async def test_read_denial_and_unsupported_history_are_not_empty_success() -> None:
    evidence, _, _ = await collect(
        {"metricAlerts": [metric()]}, statuses={"activityLogAlerts": 403, "alerts": 404}
    )
    assert len(evidence.rules) == 1 and evidence.history_coverage == "unavailable"
    assert evidence.delivery_coverage == "unavailable" and evidence.stamp.coverage == "partial"
    missing = {"activitylogalerts_read_incomplete", "alerts_read_incomplete"}
    assert missing.issubset(evidence.stamp.reasons)
    unavailable, _, _ = await collect(
        statuses={key.rsplit("/", 1)[-1]: 403 for key in AZURE_ALERT_APIS}
    )
    assert unavailable.stamp.coverage == "unavailable" and unavailable.deliveries == ()


@pytest.mark.parametrize("status", [429, 503])
async def test_throttling_stops_all_reader_and_resolver_calls(status: int) -> None:
    resolver = Resolver()
    evidence, requests, _ = await collect(statuses={"metricAlerts": status}, resolver=resolver)
    assert len(requests) == 1 and resolver.calls == []
    assert evidence.stamp.coverage == "unavailable"
    assert "collection_attempt_stopped" in evidence.stamp.reasons


async def test_total_pages_bound_is_shared_across_collections() -> None:
    evidence, requests, _ = await collect(
        {"metricAlerts": [metric()]},
        limits=AlertReadLimits(total_pages=1),
    )
    assert len(requests) == 1 and len(evidence.rules) == 1
    assert evidence.history_coverage == "unavailable" and evidence.stamp.coverage == "partial"


async def test_conflicting_resource_revisions_are_not_silently_overwritten() -> None:
    changed = metric()
    changed["properties"]["severity"] = 4
    evidence, _, _ = await collect({"metricAlerts": [metric(), changed]})
    assert evidence.rules == () and "rule_shape_or_scope_incomplete" in evidence.stamp.reasons


async def test_automation_is_preserved_as_unverified_binding_not_a_notification() -> None:
    raw = group()
    raw["properties"]["webhookReceivers"] = [
        {"name": "example-webhook", "serviceUri": "https://example.com/notify"},
    ]
    evidence, _, _ = await collect({"actionGroups": [raw]})
    assert len(evidence.groups[0].automation_refs) == 1 and len(evidence.audiences) == 1
    assert "https://example.com" not in evidence.model_dump_json()
    assert "automation_semantics_unverified" in evidence.stamp.reasons


async def test_digests_bind_all_raw_families_and_resolver_results() -> None:
    baseline = {
        "metricAlerts": [metric()],
        "actionGroups": [group()],
        "actionRules": [processing()],
    }
    first, _, source = await collect(baseline)
    same, _, _ = await collect(deepcopy(baseline))
    assert same.stamp.revision == first.stamp.revision
    for family in ("metricAlerts", "actionGroups", "actionRules"):
        changed = deepcopy(baseline)
        changed[family][0]["tags"] = {"example": "changed"}
        result, _, _ = await collect(changed)
        assert result.stamp.revision != first.stamp.revision
    changed = deepcopy(baseline)
    changed["alerts"] = [
        {
            "id": SUB + "/providers/Microsoft.AlertsManagement/alerts/example-event",
            "properties": {"essentials": {"alertRule": "example-rule"}},
        }
    ]
    history, _, _ = await collect(changed)
    resolved, _, _ = await collect(baseline, resolver=Resolver())
    assert history.stamp.revision != first.stamp.revision != resolved.stamp.revision
    assert source.opaque("content", "A") != source.opaque("content", "a")
    assert source.opaque("rule", RULE) == source.opaque("rule", RULE.upper())
    _, _, other = await collect(scope_ref="scope:other")
    assert source.opaque("audience", "binding") != other.opaque("audience", "binding")
