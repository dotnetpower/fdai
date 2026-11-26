"""No-network history and pagination fixtures; native snapshots are not delivery receipts."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from fdai.delivery.azure import alert_noise_http
from fdai.delivery.azure.alert_noise_history import attach_alert_history, pin_evidence
from fdai.delivery.azure.alert_noise_http import (
    AlertReadLimits,
    AlertReadUnavailable,
    AzureAlertReader,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.alert_noise import (
    AlertDelivery,
    AlertEvidence,
    AlertRule,
    EvidenceStamp,
)

SUB = "/subscriptions/00000000-0000-0000-0000-000000000000"
RG = SUB + "/resourceGroups/example-rg"
TARGET = RG + "/providers/Microsoft.Compute/virtualMachines/example-vm"
RULE = RG + "/providers/Microsoft.Insights/metricAlerts/example-rule"
PATH = RG + "/providers/Microsoft.AlertsManagement/alerts"
ORIGIN = "https://management.azure.com"
VERSION = "2019-03-01"
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
PARAMS = {
    "customTimeRange": "2026-09-13T12:00:00Z/2026-09-14T12:00:00Z",
    "includeContext": "false",
    "includeEgressConfig": "false",
    "pageCount": "250",
}


def opaque(kind: str, value: str) -> str:
    return kind + ":" + hashlib.sha256(value.casefold().encode()).hexdigest()


def evidence() -> AlertEvidence:
    return AlertEvidence(
        stamp=EvidenceStamp(
            source="test-source",
            tenant_ref="tenant:example",
            scope_ref="scope:example",
            revision=DIGEST,
            observed_at=NOW,
            recorded_at=NOW,
            valid_until=NOW + timedelta(minutes=15),
            coverage="complete",
            synthetic=True,
        ),
        window_start=NOW - timedelta(days=1),
        window_end=NOW,
        rules=(
            AlertRule(
                ref=opaque("rule", RULE),
                resource_ref=opaque("resource", TARGET),
                service_ref="service:unknown",
                revision=DIGEST,
                kind="metric",
            ),
        ),
    )


def history(**essentials: object) -> dict[str, Any]:
    return {
        "id": SUB + "/providers/Microsoft.AlertsManagement/alerts/example-instance",
        "type": "Microsoft.AlertsManagement/alerts",
        "properties": {
            "essentials": {
                "alertRule": RULE,
                "targetResource": TARGET,
                "startDateTime": "2026-09-14T11:00:00Z",
                "monitorCondition": "Fired",
                **essentials,
            }
        },
    }


def attach(rows: tuple[dict[str, Any], ...], *, complete: bool = True) -> AlertEvidence:
    return attach_alert_history(
        evidence(),
        rows,
        opaque=opaque,
        collection_complete=complete,
        authorized_scope=RG.casefold(),
    )


def test_native_history_cannot_manufacture_historical_rule_revision() -> None:
    result = attach((history(),))
    assert len(result.deliveries) == 1 and result.history_coverage == "partial"
    assert result.deliveries[0].rule_revision is None
    assert result.deliveries[0].state == "source"
    assert result.delivery_coverage == "unavailable"
    assert "historical_rule_revision_unavailable" in result.stamp.reasons
    assert result.stamp.revision != DIGEST and result.rules[0].revision == DIGEST
    assert RULE not in result.model_dump_json()


def test_name_only_alert_rule_is_not_guessed_from_current_unique_name() -> None:
    result = attach((history(alertRule="example-rule"),))
    assert result.history_coverage == "partial" and result.deliveries == ()
    assert "history_rule_identity_unavailable" in result.stamp.reasons


def test_native_acknowledged_state_is_not_a_verified_human_receipt() -> None:
    result = attach((history(alertState="Acknowledged", actionStatus={"isSuppressed": False}),))
    assert result.delivery_coverage == "unavailable"
    assert all(row.state == "source" and row.acknowledger_ref is None for row in result.deliveries)


def test_resolved_in_window_episode_is_not_lost_when_fired_before_window() -> None:
    result = attach(
        (
            history(
                startDateTime="2026-09-12T12:00:00Z",
                monitorCondition="Resolved",
                monitorConditionResolvedDateTime="2026-09-14T11:30:00Z",
            ),
        )
    )
    assert result.history_coverage == "partial"
    assert "historical_rule_revision_unavailable" in result.stamp.reasons


@pytest.mark.parametrize(
    "essentials",
    [
        {"alertRule": [RULE]},
        {"targetResource": True},
        {"monitorCondition": True},
        {"monitorCondition": "Unknown"},
        {"startDateTime": "2026-09-14T11:00:00"},
        {"startDateTime": "2026-09-14"},
        {"startDateTime": "2026-09-14T11:00:00.1234567Z"},
        {
            "monitorCondition": "Resolved",
            "monitorConditionResolvedDateTime": "2026-09-13T11:00:00Z",
        },
        {"monitorCondition": "Resolved"},
    ],
)
def test_malformed_native_history_is_partial_not_zero(essentials: dict[str, Any]) -> None:
    result = attach((history(**essentials),))
    assert result.history_coverage == "partial" and result.deliveries == ()
    assert "history_shape_invalid" in result.stamp.reasons


def test_missing_or_outside_rule_and_target_preserve_unknown_linkage() -> None:
    unknown = attach((history(alertRule=RULE + "-missing"),))
    outside = attach((history(targetResource=TARGET.replace("example-rg", "example-rg-other")),))
    mismatch = attach((history(targetResource=TARGET + "-other"),))
    assert "history_rule_unobserved" in unknown.stamp.reasons
    assert "history_target_outside_scope" in outside.stamp.reasons
    assert "history_target_unrepresented" in mismatch.stamp.reasons
    assert all(result.history_coverage == "partial" for result in (unknown, outside, mismatch))


def test_successful_empty_history_is_distinct_from_failed_empty_collection() -> None:
    empty = attach(())
    assert empty.history_coverage == "complete" and empty.deliveries == ()
    assert empty.delivery_coverage == "unavailable"
    assert evidence().history_coverage == "unavailable"
    missing = attach((), complete=False)
    assert missing.history_coverage == "unavailable"
    assert "history_collection_partial" in missing.stamp.reasons


def test_history_content_order_and_provenance_are_deterministic() -> None:
    first, second = history(), history(alertRule="example-rule")
    second["id"] += "-second"
    result = attach((first, second))
    reordered = attach((second, first))
    assert result.stamp.revision == reordered.stamp.revision
    changed = deepcopy(first)
    changed["properties"]["essentials"]["description"] = "changed source content"
    assert attach((changed, second)).stamp.revision != result.stamp.revision
    assert attach((first, first)).history_coverage == "partial"


def test_native_history_preserves_existing_independent_delivery_records() -> None:
    original = evidence()
    delivery = AlertDelivery(
        ref="event:observed",
        episode_ref="episode:observed",
        rule_ref=original.rules[0].ref,
        rule_revision=DIGEST,
        condition="fired",
        state="source",
        event_at=NOW - timedelta(hours=1),
        receipt_ref="receipt:observed",
    )
    original = AlertEvidence.model_validate({**original.model_dump(), "deliveries": (delivery,)})
    result = attach_alert_history(original, (history(),), opaque=opaque)
    assert delivery in result.deliveries
    assert len(result.deliveries) == 2


def test_pinning_includes_all_normalized_evidence_fields() -> None:
    original = evidence()
    before = pin_evidence(original, source_digest="source:a")
    changed = AlertEvidence.model_validate(
        {**original.model_dump(), "delivery_coverage": "partial"}
    )
    assert pin_evidence(changed, source_digest="source:a").stamp.revision != before.stamp.revision
    assert pin_evidence(original, source_digest="source:b").stamp.revision != before.stamp.revision


class Identity:
    def __init__(self, *, invalid: str | None = None) -> None:
        self.invalid = invalid

    async def get_token(self, audience: str) -> IdentityToken:
        if self.invalid == "error":
            raise RuntimeError("private credential message")
        expiry = NOW if self.invalid == "expired" else NOW + timedelta(minutes=5)
        return IdentityToken(
            "synthetic-token", expiry, "wrong-audience" if self.invalid == "audience" else audience
        )


def cursor(**changes: str) -> str:
    return (
        ORIGIN
        + PATH
        + "?"
        + urlencode(
            {
                "api-version": VERSION,
                **PARAMS,
                "$skiptoken": "next",
                **changes,
            }
        )
    )


async def test_two_history_pages_preserve_scope_version_and_original_query() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.path == PATH
        assert request.url.params["customTimeRange"] == PARAMS["customTimeRange"]
        assert request.headers["authorization"] == "Bearer synthetic-token"
        body: dict[str, Any] = {"value": [{"page": len(requests)}]}
        if len(requests) == 1:
            body["nextLink"] = cursor()
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        rows = await reader.list(PATH, api_version=VERSION, params=PARAMS)
    assert rows == ({"page": 1}, {"page": 2}) and len(requests) == 2


@pytest.mark.parametrize(
    "link",
    [
        "https://example.com/collect?api-version=" + VERSION,
        cursor().replace("management.azure.com", "management.azure.com.example.com"),
        cursor().replace("management.azure.com", "user@management.azure.com"),
        cursor().replace("management.azure.com", "management.azure.com:443"),
        cursor().replace("https:", "http:"),
        cursor().replace("example-rg", "example-rg-other"),
        cursor().replace("/alerts?", "/alerts/../alerts?"),
        cursor().replace("/providers/", "%2fproviders/"),
        cursor() + "#fragment",
        cursor() + "#",
        cursor() + "&api-version=" + VERSION,
        cursor() + "&API-VERSION=" + VERSION,
        cursor(customTimeRange="2026-09-01T00:00:00Z/2026-09-14T12:00:00Z"),
        cursor(includeContext="true"),
        cursor(targetResource="outside-resource"),
        ORIGIN + PATH + "?api-version=" + VERSION + "&$skiptoken=next",
        cursor().replace("https://", "\nhttps://"),
        "",
        False,
    ],
)
async def test_history_pagination_cannot_escape_or_widen_read_scope(link: object) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"value": [{"page": 1}], "nextLink": link})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        with pytest.raises(AlertReadUnavailable) as failure:
            await reader.list(PATH, api_version=VERSION, params=PARAMS)
    assert len(calls) == 1 and failure.value.rows == ({"page": 1},)
    assert "example.com" not in str(failure.value)


@pytest.mark.parametrize(
    ("limits", "body", "reason", "kept"),
    [
        (
            AlertReadLimits(pages=1),
            {"value": [{"a": 1}], "nextLink": cursor()},
            "provider_pages_exceeded",
            1,
        ),
        (AlertReadLimits(items=1), {"value": [{"a": 1}, {"a": 2}]}, "provider_items_exceeded", 1),
        (
            AlertReadLimits(total_items=1),
            {"value": [{"a": 1}, {"a": 2}]},
            "total_items_exceeded",
            1,
        ),
        (
            AlertReadLimits(bytes_per_page=32),
            {"value": [{"private": "x" * 100}]},
            "provider_bytes_exceeded",
            0,
        ),
        (
            AlertReadLimits(total_bytes=32),
            {"value": [{"private": "x" * 100}]},
            "total_bytes_exceeded",
            0,
        ),
    ],
)
async def test_history_page_item_and_byte_budgets_are_explicit(
    limits: AlertReadLimits,
    body: dict[str, Any],
    reason: str,
    kept: int,
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        reader = AzureAlertReader(
            http=client, identity=Identity(), limits=limits, clock=lambda: NOW
        )
        with pytest.raises(AlertReadUnavailable, match=reason) as failure:
            await reader.list(PATH, api_version=VERSION, params=PARAMS)
    assert len(failure.value.rows) == kept


@pytest.mark.parametrize(
    "payload",
    [
        b'{"value":[],"value":[]}',
        b'{"value":[{"threshold":NaN}]}',
        b'{"value":[{"threshold":1e9999}]}',
        b'{"value":[true]}',
        b'{"value":{}}',
        b"not-json",
    ],
)
async def test_history_transport_rejects_non_native_json_and_nonfinite_values(
    payload: bytes,
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        with pytest.raises(AlertReadUnavailable):
            await reader.list(PATH, api_version=VERSION, params=PARAMS)


async def test_pagination_cycle_fails_without_retrying_seen_cursor() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"value": [], "nextLink": cursor()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(AlertReadUnavailable, match="pagination_cycle"):
            await AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW).list(
                PATH,
                api_version=VERSION,
                params=PARAMS,
            )
    assert len(calls) == 2


@pytest.mark.parametrize("invalid", ["expired", "audience", "error"])
async def test_invalid_identity_never_reaches_management_endpoint(invalid: str) -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid identity MUST not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(
            http=client, identity=Identity(invalid=invalid), clock=lambda: NOW
        )
        with pytest.raises(AlertReadUnavailable, match="reader_identity_invalid") as failure:
            await reader.list(PATH, api_version=VERSION, params=PARAMS)
    assert "private credential" not in str(failure.value)


async def test_unapproved_api_path_or_version_is_rejected_before_authentication() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        for path, version, params in [
            (SUB + "/providers/Microsoft.AlertsManagement/alerts", VERSION, PARAMS),
            (PATH, "2026-01-01", PARAMS),
            (PATH + "/testNotifications", VERSION, PARAMS),
            (PATH, VERSION, {"api-version": "different"}),
            (PATH, VERSION, {"includeContext": "true"}),
        ]:
            with pytest.raises(ValueError):
                await reader.list(path, api_version=version, params=params)


async def test_provider_timeout_stops_shared_attempt_without_a_retry() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("private-provider-body", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        budget = reader.new_budget()
        for _ in range(2):
            with pytest.raises(AlertReadUnavailable, match="provider_timeout"):
                await reader.list(PATH, api_version=VERSION, params=PARAMS, budget=budget)
    assert len(calls) == 1


async def test_second_page_failure_keeps_prior_rows_without_claiming_completion() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"value": [{"page": 1}], "nextLink": cursor()})
        return httpx.Response(503, text="private provider body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        with pytest.raises(AlertReadUnavailable, match="provider_status_503") as failure:
            await reader.list(PATH, api_version=VERSION, params=PARAMS)
    assert len(calls) == 2 and failure.value.rows == ({"page": 1},)
    assert failure.value.terminal and "private provider body" not in str(failure.value)


async def test_total_deadline_is_enforced_before_another_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        raise AssertionError("expired budget MUST not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        reader = AzureAlertReader(http=client, identity=Identity(), clock=lambda: NOW)
        budget = reader.new_budget()
        budget._started = 0.0
        monkeypatch.setattr(alert_noise_http, "time", SimpleNamespace(monotonic=lambda: 100.0))
        with pytest.raises(AlertReadUnavailable, match="total_deadline_exceeded"):
            await reader.list(PATH, api_version=VERSION, params=PARAMS, budget=budget)
