from __future__ import annotations

import pytest

from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    evaluate_incident_auto_open,
    open_detected_incident_candidate,
)
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "incident_correlation": "correlate",
        "correlation_id": "episode-1",
        "evidence_key": "evidence-1",
        "resource_id": "api-example",
        "event_type": "availability.probe_failed",
        "severity": "high",
    }
    candidate.update(overrides)
    return candidate


def test_default_policy_holds_medium_candidate_and_accepts_high() -> None:
    policy = IncidentAutoOpenPolicy()

    medium = evaluate_incident_auto_open(_candidate(severity="medium"), policy)
    high = evaluate_incident_auto_open(_candidate(severity="high"), policy)

    assert medium.eligible is False
    assert medium.reason == "severity_below_minimum"
    assert high.eligible is True
    assert high.severity is IncidentSeverity.SEV2


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"incident_correlation": "none"}, "incident_correlation_disabled"),
        ({"correlation_id": ""}, "correlation_missing"),
        ({"evidence_key": ""}, "evidence_missing"),
        ({"resource_id": ""}, "resource_missing"),
        ({"event_type": ""}, "event_type_missing"),
    ],
)
def test_policy_rejects_candidates_without_authority_or_evidence(
    overrides: dict[str, object], reason: str
) -> None:
    decision = evaluate_incident_auto_open(_candidate(**overrides), IncidentAutoOpenPolicy())

    assert decision.eligible is False
    assert decision.reason == reason


def test_disabled_policy_holds_even_critical_candidate() -> None:
    decision = evaluate_incident_auto_open(
        _candidate(severity="critical"),
        IncidentAutoOpenPolicy(enabled=False),
    )

    assert decision.eligible is False
    assert decision.reason == "auto_open_disabled"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("critical", IncidentSeverity.SEV1),
        ("sev2", IncidentSeverity.SEV2),
        ("medium", IncidentSeverity.SEV3),
        ("low", IncidentSeverity.SEV4),
        ("info", IncidentSeverity.SEV5),
    ],
)
def test_policy_maps_recorded_severity(label: str, expected: IncidentSeverity) -> None:
    policy = IncidentAutoOpenPolicy(minimum_severity=IncidentSeverity.SEV5)

    decision = evaluate_incident_auto_open(_candidate(severity=label), policy)

    assert decision.eligible is True
    assert decision.severity is expected


async def test_shared_helper_holds_medium_candidate_without_writing() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(
        registry=registry,
        allowed_agent_principals={"Heimdall"},
    )

    result = await open_detected_incident_candidate(
        workflow=workflow,
        candidate=_candidate(severity="medium"),
        policy=IncidentAutoOpenPolicy(),
    )

    assert result is None
    assert registry.snapshot() == {}


async def test_shared_helper_opens_high_candidate_once_with_recorded_severity() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(
        registry=registry,
        allowed_agent_principals={"Heimdall"},
    )
    candidate = _candidate(severity="high")

    first = await open_detected_incident_candidate(
        workflow=workflow,
        candidate=candidate,
        policy=IncidentAutoOpenPolicy(),
    )
    replay = await open_detected_incident_candidate(
        workflow=workflow,
        candidate=candidate,
        policy=IncidentAutoOpenPolicy(),
    )

    assert first is not None and first.created is True
    assert replay is not None and replay.created is False
    assert first.incident.severity is IncidentSeverity.SEV2
    assert len(registry.snapshot()) == 1
