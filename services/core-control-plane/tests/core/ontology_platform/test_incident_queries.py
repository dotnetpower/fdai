"""Read-only Incident evidence FunctionType contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    INCIDENT_EVIDENCE_PURPOSE,
    incident_evidence_function,
    incident_evidence_function_type,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryStateStore

INCIDENT_ID = "00000000-0000-0000-0000-000000000101"
CORRELATION_ID = "incident-correlation-101"


class _IncidentEvidenceReader:
    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        assert correlation_id == CORRELATION_ID
        assert limit == 20
        return (
            (
                {
                    "seq": 1,
                    "event_id": "00000000-0000-0000-0000-000000000201",
                    "correlation_id": CORRELATION_ID,
                    "actor": "Heimdall",
                    "action_kind": "incident.open",
                    "mode": "shadow",
                    "recorded_at": "2026-08-14T09:00:00Z",
                    "entry": {
                        "incident_id": INCIDENT_ID,
                        "severity": "sev2",
                        "state": "open",
                    },
                },
                {
                    "seq": 2,
                    "event_id": "00000000-0000-0000-0000-000000000202",
                    "correlation_id": CORRELATION_ID,
                    "actor": "operator@example.com",
                    "action_kind": "incident.transition",
                    "mode": "shadow",
                    "recorded_at": "2026-08-14T09:05:00Z",
                    "entry": {
                        "incident_id": INCIDENT_ID,
                        "severity": "sev2",
                        "to_state": "triaging",
                    },
                },
                {
                    "seq": 3,
                    "event_id": "00000000-0000-0000-0000-000000000203",
                    "correlation_id": CORRELATION_ID,
                    "actor": "fdai.core.rca",
                    "action_kind": "rca.hypothesis",
                    "mode": "shadow",
                    "recorded_at": "2026-08-14T09:06:00Z",
                    "entry": {
                        "incident_id": INCIDENT_ID,
                        "rca_tier": "t0",
                        "rca_outcome": "grounded",
                        "rca_cause": "A required owner tag was absent.",
                        "rca_confidence": 0.95,
                        "rca_reason": "Matched the deterministic owner-tag rule.",
                        "rca_citations": [
                            {"kind": "rule", "ref": "object-storage.owner-tag.required"}
                        ],
                        "rca_impact": [
                            {
                                "metric": "noncompliant_resources",
                                "baseline": 0,
                                "observed": 1,
                                "threshold": 0,
                                "unit": "resources",
                                "impact": "One resource is outside the required baseline.",
                                "evidence_ref": "audit:3",
                            }
                        ],
                    },
                },
            ),
            False,
        )


class _UngroundedIncidentEvidenceReader:
    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        rows, truncated = await _IncidentEvidenceReader().list_incident_evidence(
            correlation_id=correlation_id,
            limit=limit,
        )
        hypothesis = {**rows[-1], "entry": {**rows[-1]["entry"], "rca_citations": []}}
        return (*rows[:-1], hypothesis), truncated


class _NotificationRouteIncidentEvidenceReader:
    def __init__(self, outcome: str) -> None:
        self._outcome = outcome

    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        rows, truncated = await _IncidentEvidenceReader().list_incident_evidence(
            correlation_id=correlation_id,
            limit=limit,
        )
        route = {
            **rows[-1],
            "actor": "fdai.core.notifications.router",
            "action_kind": "notification.route",
            "entry": {
                "incident_id": INCIDENT_ID,
                "outcome": self._outcome,
                "route_category": "operational_alert",
            },
        }
        return (*rows[:-1], route), truncated


async def test_incident_evidence_returns_recorded_grounded_rca() -> None:
    declaration = incident_evidence_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        incident_evidence_function(release, reader=_IncidentEvidenceReader()),
    )

    result, receipt = await registry.invoke_with_receipt(
        INCIDENT_EVIDENCE_FUNCTION_NAME,
        {
            "incident_id": INCIDENT_ID,
            "correlation_id": CORRELATION_ID,
            "limit": 20,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(INCIDENT_EVIDENCE_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert result["correlation_id"] == CORRELATION_ID
    assert result["incident_profile"] == {
        "correlation_id": CORRELATION_ID,
        "incident_id": INCIDENT_ID,
        "ticket_id": None,
        "title": None,
        "severity": "sev2",
        "status": "triaging",
        "vertical": None,
        "opened_at": "2026-08-14T09:00:00Z",
        "last_updated_at": "2026-08-14T09:06:00Z",
        "duration_seconds": 360.0,
        "audit_records": 3,
        "actors": ["Heimdall", "fdai.core.rca", "operator@example.com"],
        "modes": ["shadow"],
    }
    assert result["correlated_evidence"] == [
        {
            "audit_ref": "audit:1",
            "event_id": "00000000-0000-0000-0000-000000000201",
            "actor": "Heimdall",
            "action_kind": "incident.open",
            "mode": "shadow",
            "recorded_at": "2026-08-14T09:00:00Z",
        },
        {
            "audit_ref": "audit:2",
            "event_id": "00000000-0000-0000-0000-000000000202",
            "actor": "operator@example.com",
            "action_kind": "incident.transition",
            "mode": "shadow",
            "recorded_at": "2026-08-14T09:05:00Z",
        },
        {
            "audit_ref": "audit:3",
            "event_id": "00000000-0000-0000-0000-000000000203",
            "actor": "fdai.core.rca",
            "action_kind": "rca.hypothesis",
            "mode": "shadow",
            "recorded_at": "2026-08-14T09:06:00Z",
        },
    ]
    assert result["root_cause"] == {
        "tier": "t0",
        "outcome": "grounded",
        "cause": "A required owner tag was absent.",
        "confidence": 0.95,
        "reason": "Matched the deterministic owner-tag rule.",
        "remediation_ref": None,
        "mode": "shadow",
        "recorded_at": "2026-08-14T09:06:00Z",
        "causal_hops": [],
    }
    assert result["impact_evidence"] == [
        {
            "metric": "noncompliant_resources",
            "baseline": 0,
            "observed": 1,
            "threshold": 0,
            "unit": "resources",
            "impact": "One resource is outside the required baseline.",
            "evidence_ref": "audit:3",
        }
    ]
    assert result["grounded_citations"] == [
        {
            "tier": "t0",
            "kind": "rule",
            "ref": "object-storage.owner-tag.required",
            "summary": None,
            "source_at": None,
            "freshness": None,
            "recorded_at": "2026-08-14T09:06:00Z",
        }
    ]
    assert result["evidence_gaps"] == []
    assert result["cause_claim_supported"] is True
    assert result["execution_authority"] is False
    assert '"cause": "A required owner tag was absent."' in json.dumps(result, sort_keys=True)
    assert receipt.function_ref.name == INCIDENT_EVIDENCE_FUNCTION_NAME
    assert receipt.evidence_refs == ()
    assert INCIDENT_EVIDENCE_FUNCTION_NAME in {item.name for item in operational_function_types(())}


async def test_incident_evidence_does_not_promote_an_uncited_cause() -> None:
    declaration = incident_evidence_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        incident_evidence_function(release, reader=_UngroundedIncidentEvidenceReader()),
    )

    result, _ = await registry.invoke_with_receipt(
        INCIDENT_EVIDENCE_FUNCTION_NAME,
        {
            "incident_id": INCIDENT_ID,
            "correlation_id": CORRELATION_ID,
            "limit": 20,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(INCIDENT_EVIDENCE_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert result["root_cause"] is None
    assert result["grounded_citations"] == []
    assert result["cause_claim_supported"] is False
    assert result["evidence_gaps"] == ["root_cause_missing", "grounded_citations_missing"]


async def test_incident_evidence_projects_a_recorded_notification_terminal_failure() -> None:
    declaration = incident_evidence_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        incident_evidence_function(
            release,
            reader=_NotificationRouteIncidentEvidenceReader("route_unresolved"),
        ),
    )

    result, _ = await registry.invoke_with_receipt(
        INCIDENT_EVIDENCE_FUNCTION_NAME,
        {
            "incident_id": INCIDENT_ID,
            "correlation_id": CORRELATION_ID,
            "limit": 20,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(INCIDENT_EVIDENCE_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert result["root_cause"] == {
        "tier": "t0",
        "outcome": "grounded",
        "cause": (
            "Notification delivery failed because the configured route has no resolvable channels."
        ),
        "confidence": 1.0,
        "reason": "Recorded notification route outcome: route_unresolved.",
        "remediation_ref": None,
        "mode": "shadow",
        "recorded_at": "2026-08-14T09:06:00Z",
        "causal_hops": [],
        "next_safe_step": "configure_notification_route",
    }
    assert result["impact_evidence"] == [
        {
            "metric": "notification_delivery_outcome",
            "baseline": "delivered",
            "observed": "route_unresolved",
            "threshold": "delivered",
            "unit": "route_outcome",
            "impact": (
                "Operational notification delivery did not complete and was escalated for "
                "human attention."
            ),
            "evidence_ref": "audit:3",
        }
    ]
    assert result["grounded_citations"] == [
        {
            "tier": "t0",
            "kind": "event",
            "ref": "audit:3",
            "summary": "Recorded notification route outcome: route_unresolved.",
            "source_at": "2026-08-14T09:06:00Z",
            "freshness": "recorded",
            "recorded_at": "2026-08-14T09:06:00Z",
        }
    ]
    assert result["evidence_gaps"] == []
    assert result["cause_claim_supported"] is True
    assert result["execution_authority"] is False


async def test_incident_evidence_does_not_promote_successful_notification_delivery() -> None:
    declaration = incident_evidence_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        incident_evidence_function(
            release,
            reader=_NotificationRouteIncidentEvidenceReader("delivered"),
        ),
    )

    result, _ = await registry.invoke_with_receipt(
        INCIDENT_EVIDENCE_FUNCTION_NAME,
        {
            "incident_id": INCIDENT_ID,
            "correlation_id": CORRELATION_ID,
            "limit": 20,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=(INCIDENT_EVIDENCE_PURPOSE,),
        ),
    )

    assert isinstance(result, dict)
    assert result["root_cause"] is None
    assert result["impact_evidence"] == []
    assert result["grounded_citations"] == []
    assert result["evidence_gaps"] == [
        "root_cause_missing",
        "impact_evidence_missing",
        "grounded_citations_missing",
    ]
    assert result["cause_claim_supported"] is False


async def test_in_memory_reader_scopes_rows_and_reports_truncation() -> None:
    store = InMemoryStateStore()
    for index, correlation_id in enumerate(
        (CORRELATION_ID, CORRELATION_ID, "other-incident"), start=1
    ):
        await store.append_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-{index:012d}",
                "correlation_id": correlation_id,
                "actor": "Saga",
                "action_kind": "incident.evidence",
                "mode": "shadow",
                "recorded_at": datetime(2026, 8, 14, 9, index, tzinfo=UTC).isoformat(),
            }
        )

    rows, truncated = await store.list_incident_evidence(
        correlation_id=CORRELATION_ID,
        limit=1,
    )

    assert truncated is True
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == CORRELATION_ID
    assert rows[0]["seq"] == 2
