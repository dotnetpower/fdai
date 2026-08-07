from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.operator_api.application.conversation.capabilities.preincident_activity import (
    PreIncidentActivityRequest,
    parse_preincident_activity,
    resolve_preincident_activity,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    contextualize_resource_followup,
    parse_resource_context,
)
from fdai.delivery.operator_api.projections.conversation.resource_context import (
    response_resource_context,
)

ANCHOR = datetime(2026, 8, 1, 2, tzinfo=UTC)


def _request(*, locale: str = "en") -> PreIncidentActivityRequest:
    return PreIncidentActivityRequest(
        resource_name="vm-primary",
        resource_group="rg-example",
        before_at=ANCHOR,
        locale=locale,
    )


def test_parse_preincident_activity_accepts_only_canonical_aware_request() -> None:
    parsed = parse_preincident_activity(
        "vm-primary change history: pre-incident activity "
        "group=rg-example before=2026-08-01T02:00:00Z locale=en"
    )

    assert parsed == _request()
    assert parse_preincident_activity("What changed before the incident?") is None
    assert (
        parse_preincident_activity(
            "vm-primary change history: pre-incident activity "
            "group=rg-example before=2026-08-01T02:00:00 locale=en"
        )
        is None
    )


def test_parse_preincident_activity_accepts_missing_anchor_canonical() -> None:
    parsed = parse_preincident_activity(
        "vm-primary change history: pre-incident activity anchor=unavailable locale=ko"
    )

    assert parsed is not None
    assert parsed.resource_name == "vm-primary"
    assert parsed.locale == "ko"


def test_contextualize_preincident_followup_uses_complete_server_anchor() -> None:
    contextualized, used_context = contextualize_resource_followup(
        "What changed immediately before the incident?",
        {
            "name": "vm-primary",
            "resource_type": "microsoft.compute.virtualmachines",
            "evidence_ref": "subscription-health:resource-health@2026-08-01T02:05:00Z",
            "resource_group": "rg-example",
            "event_at": "2026-08-01T02:00:00Z",
            "event_status": "Unavailable",
        },
    )

    assert used_context is True
    assert contextualized == (
        "vm-primary change history: pre-incident activity "
        "group=rg-example before=2026-08-01T02:00:00Z locale=en"
    )


def test_resource_context_rejects_incomplete_incident_anchor() -> None:
    try:
        parse_resource_context(
            {
                "name": "vm-primary",
                "resource_type": "microsoft.compute.virtualmachines",
                "evidence_ref": "subscription-health:resource-health@2026-08-01T02:05:00Z",
                "resource_group": "rg-example",
                "event_at": "2026-08-01T02:00:00Z",
            }
        )
    except ValueError as exc:
        assert str(exc) == "resource_context incident anchor MUST be bounded and complete"
    else:
        raise AssertionError("incomplete incident anchor must be rejected")


def test_response_never_echoes_unverified_resource_selector_fallback() -> None:
    fallback = {
        "name": "fabricated-resource",
        "resource_type": "compute.vm",
        "evidence_ref": "inventory:forged@2026-08-03T00:00:00Z",
    }

    assert response_resource_context({}, fallback) is None


async def test_resolve_preincident_activity_filters_to_successful_group_writes() -> None:
    async def provider(lookback_seconds: int, max_events: int) -> dict[str, object]:
        assert lookback_seconds == 86_400
        assert max_events == 200
        return {
            "status": "matched",
            "source": "azure-activity-log",
            "observed_at": "2026-08-01T02:05:00Z",
            "truncated": False,
            "events": [
                {
                    "resource_group": "rg-example",
                    "occurred_at": "2026-08-01T01:30:00Z",
                    "status": "Succeeded",
                    "operation": "Microsoft.Compute/virtualMachines/write",
                    "name": "vm-primary\nforged",
                    "type": "Microsoft.Compute/virtualMachines",
                },
                {
                    "resource_group": "rg-other",
                    "occurred_at": "2026-08-01T01:45:00Z",
                    "status": "Succeeded",
                    "operation": "Microsoft.Compute/virtualMachines/write",
                },
                {
                    "resource_group": "rg-example",
                    "occurred_at": "2026-08-01T01:50:00Z",
                    "status": "Failed",
                    "operation": "Microsoft.Compute/virtualMachines/write",
                },
                {
                    "resource_group": "rg-example",
                    "occurred_at": "2026-08-01T01:55:00",
                    "status": "Succeeded",
                    "operation": "Microsoft.Compute/virtualMachines/write",
                },
                {
                    "resource_group": "rg-example",
                    "occurred_at": "2026-08-01T02:00:00Z",
                    "status": "Succeeded",
                    "operation": "Microsoft.Compute/virtualMachines/write",
                },
            ],
        }

    result = await resolve_preincident_activity(_request(), provider)

    assert result["facts"] == {
        "status": "matched",
        "intent": "pre_incident_changes",
        "resource_name": "vm-primary",
        "resource_group": "rg-example",
        "before_at": "2026-08-01T02:00:00Z",
        "immediate_count": 1,
        "matched_count": 1,
        "truncated": False,
        "evidence_refs": ("activity:azure-activity-log@2026-08-01T02:05:00Z",),
        "evidence_sources": ("azure-activity-log",),
    }
    assert "vm-primary forged" in str(result["answer"])
    assert "\nforged" not in str(result["answer"])
    assert "Pre-incident change timeline:" in str(result["answer"])
    assert "2026-08-01T01:00:00Z: Start of analysis window." in str(result["answer"])
    assert "2026-08-01T02:00:00Z: Incident anchor." in str(result["answer"])


async def test_resolve_preincident_activity_rejects_invalid_provenance() -> None:
    async def provider(lookback_seconds: int, max_events: int) -> dict[str, object]:
        del lookback_seconds, max_events
        return {
            "status": "matched",
            "source": "azure activity log\nforged",
            "observed_at": "not-a-timestamp",
            "events": [],
        }

    result = await resolve_preincident_activity(_request(), provider)

    assert result["facts"] == {
        "status": "unavailable",
        "intent": "pre_incident_changes",
        "resource_name": "vm-primary",
        "reason": "activity_provenance_invalid",
        "evidence_refs": (),
        "evidence_sources": (),
    }


async def test_resolve_preincident_activity_reports_truncation_and_bounds_output() -> None:
    async def provider(lookback_seconds: int, max_events: int) -> dict[str, object]:
        del lookback_seconds, max_events
        return {
            "status": "matched",
            "source": "azure-activity-log",
            "observed_at": "2026-08-01T02:05:00Z",
            "truncated": True,
            "events": [
                {
                    "resource_group": "rg-example",
                    "occurred_at": f"2026-08-01T01:{minute:02d}:00Z",
                    "status": "Succeeded",
                    "operation": "write",
                    "name": f"change-{minute}",
                }
                for minute in range(30)
            ],
        }

    result = await resolve_preincident_activity(_request(), provider)

    facts = result["facts"]
    assert isinstance(facts, dict)
    assert facts["immediate_count"] == 30
    assert facts["truncated"] is True
    assert str(result["answer"]).count("- Change ") == 20
    assert "result is truncated" in str(result["answer"])


async def test_resolve_preincident_activity_fails_closed_on_provider_error() -> None:
    async def provider(lookback_seconds: int, max_events: int) -> dict[str, object]:
        del lookback_seconds, max_events
        raise RuntimeError("reader unavailable")

    result = await resolve_preincident_activity(_request(), provider)

    facts = result["facts"]
    assert isinstance(facts, dict)
    assert facts["status"] == "unavailable"
    assert facts["reason"] == "RuntimeError"
    assert facts["evidence_refs"] == ()


async def test_resolve_preincident_activity_fails_closed_without_anchor() -> None:
    request = parse_preincident_activity(
        "vm-primary change history: pre-incident activity anchor=unavailable locale=en"
    )
    assert request is not None

    result = await resolve_preincident_activity(request, None)

    facts = result["facts"]
    assert isinstance(facts, dict)
    assert facts["status"] == "unavailable"
    assert facts["reason"] == "incident_anchor_unavailable"
    assert facts["evidence_refs"] == ()
