"""Observation-only resource stops, declared intent and positive recovery."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.investigation.resource_availability import ResourceAvailabilityAnalyzer
from fdai.core.investigation.resource_availability_evidence import (
    AvailabilityUnavailableReason,
    PlannedStopWindow,
    ResourceAvailabilityEvidence,
    ResourceAvailabilityPolicy,
    ResourceOperationalState,
    assess_resource_availability,
)
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
REF = "scope-example/resource-group/example/compute/example"
SCOPE = "scope-example"
SINCE = NOW - timedelta(minutes=5)
RUNNING = ResourceOperationalState.RUNNING
STOPPED = ResourceOperationalState.STOPPED


def _evidence(**changes: object) -> ResourceAvailabilityEvidence:
    return replace(
        ResourceAvailabilityEvidence(
            resource_ref=REF,
            resource_type="compute.vm",
            scope_ref=SCOPE,
            state=STOPPED,
            observed_at=NOW - timedelta(seconds=30),
            recorded_at=NOW,
            source_revision="example-snapshot",
            evidence_ref="inventory:example-snapshot:resource:example",
        ),
        **changes,
    )


def _policy(**changes: object) -> ResourceAvailabilityPolicy:
    return replace(ResourceAvailabilityPolicy(frozenset({"compute.vm"})), **changes)


def _assess(
    evidence: ResourceAvailabilityEvidence,
    policy: ResourceAvailabilityPolicy | None = None,
):
    return assess_resource_availability(
        evidence,
        resource_ref=REF,
        resource_type="compute.vm",
        scope_ref=SCOPE,
        since=SINCE,
        until=NOW,
        policy=policy or _policy(),
    )


def test_observed_stop_never_invents_desired_running_or_failure_cause() -> None:
    result = _assess(_evidence())
    assert result.status == "stop_observed"
    assert result.evidence_complete
    assert result.recovery_closed is False
    assert _policy().expected_state is None


@pytest.mark.parametrize(
    ("observed", "expected", "status", "recovered"),
    [
        (RUNNING, None, "running_observed", None),
        (STOPPED, RUNNING, "expected_running_not_observed", False),
        (STOPPED, STOPPED, "expected_stop_observed", None),
        (RUNNING, STOPPED, "expected_stop_not_observed", False),
    ],
)
def test_expected_state_requires_declaration_and_positive_recovery(
    observed, expected, status, recovered
) -> None:
    policy = _policy(
        expected_state=expected,
        expectation_ref="policy:example" if expected else None,
    )
    result = _assess(_evidence(state=observed), policy)
    assert result.status == status
    assert result.recovery_closed is recovered


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"resource_ref": "another-resource"}, "identity_mismatch"),
        ({"resource_type": "mysql-server"}, "identity_mismatch"),
        ({"scope_ref": "another-scope"}, "identity_mismatch"),
        ({"source_revision": None}, "provenance_missing"),
        ({"evidence_ref": None}, "provenance_missing"),
        ({"observed_at": None}, "observation_time_missing"),
        ({"observed_at": SINCE - timedelta(seconds=1)}, "stale"),
        ({"observed_at": NOW + timedelta(seconds=1)}, "observation_time_invalid"),
        ({"recorded_at": SINCE}, "observation_time_invalid"),
        ({"state": ResourceOperationalState.UNKNOWN}, "unknown"),
        (
            {"unavailable_reason": AvailabilityUnavailableReason.AUTHORIZATION_DENIED},
            "authorization_denied",
        ),
        (
            {"unavailable_reason": AvailabilityUnavailableReason.RESOURCE_MISSING},
            "resource_missing",
        ),
    ],
)
def test_bad_or_missing_evidence_is_not_healthy(changes, status) -> None:
    result = _assess(_evidence(**{"state": RUNNING, **changes}))
    assert result.status == status
    assert not result.evidence_complete
    assert result.recovery_closed is None


def test_unmanaged_resource_does_not_acquire_an_expectation() -> None:
    result = _assess(_evidence(), ResourceAvailabilityPolicy(frozenset({"mysql-server"})))
    assert result.status == "not_monitored"
    assert not result.evidence_complete
    assert result.recovery_closed is None


@pytest.mark.parametrize("maintenance", [False, True])
def test_attributed_planned_stops_are_not_unplanned_failure_or_recovery(maintenance) -> None:
    window = PlannedStopWindow(
        REF, SINCE, NOW + timedelta(minutes=5), "maintenance:example", maintenance
    )
    result = _assess(
        _evidence(),
        _policy(expected_state=RUNNING, expectation_ref="policy:running", planned_stops=(window,)),
    )
    assert result.status == (
        "maintenance_stop_observed" if maintenance else "planned_stop_observed"
    )
    assert result.evidence_complete
    assert result.recovery_closed is None


@pytest.mark.parametrize("case", ["other_target", "ended", "not_started", "predates_plan"])
def test_plan_only_applies_to_its_exact_target_and_current_observation(case) -> None:
    window = PlannedStopWindow(REF, SINCE, NOW + timedelta(minutes=1), "plan:example")
    if case == "other_target":
        window = replace(window, resource_ref="another-resource")
    elif case == "ended":
        window = replace(window, until=NOW)
    elif case == "not_started":
        window = replace(window, since=NOW + timedelta(seconds=1))
    else:
        window = replace(window, since=NOW - timedelta(seconds=10))
    result = _assess(_evidence(), _policy(planned_stops=(window,)))
    assert result.status == "stop_observed"


def test_policy_does_not_accept_unattributed_expected_state() -> None:
    with pytest.raises(ValueError, match="provenance"):
        _policy(expected_state=RUNNING)


async def test_analyzer_carries_replayable_inputs_and_no_remediation_authority() -> None:
    evidence = _evidence()

    class Source:
        async def observe(self, *, resource_ref, since, until):
            assert (resource_ref, since, until) == (REF, SINCE, NOW)
            return evidence

    analyzer = ResourceAvailabilityAnalyzer(
        resource_kind="virtual_machine",
        resource_type="compute.vm",
        scope_ref=SCOPE,
        source=Source(),
        policy=_policy(),
        wall_clock=lambda: NOW,
    )
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.remediation_ref is None
    assert finding.signal == "resource_availability"
    assert finding.assessment is not None
    assert finding.assessment.recovery_closed is False
    replay = json.loads(finding.metadata["assessment_input"])
    saved = replay["evidence"]
    saved["state"] = ResourceOperationalState(saved["state"])
    for field in ("observed_at", "recorded_at"):
        saved[field] = datetime.fromisoformat(saved[field])
    repeated = _assess(ResourceAvailabilityEvidence(**saved))
    assert asdict(repeated) == {
        key: value for key, value in asdict(finding.assessment).items() if key != "assessed_by"
    }


async def test_routine_healthy_observations_do_not_create_findings() -> None:
    class Source:
        async def observe(self, **kwargs):
            return _evidence(state=RUNNING)

    analyzer = ResourceAvailabilityAnalyzer(
        resource_kind="virtual_machine",
        resource_type="compute.vm",
        scope_ref=SCOPE,
        source=Source(),
        policy=_policy(),
        wall_clock=lambda: NOW,
    )
    assert not await analyzer.analyze(resource_ref=REF, window_seconds=300)


@pytest.mark.parametrize("fresh", [True, False])
async def test_recovery_requires_prior_actual_fault_and_later_positive_observation(fresh) -> None:
    class Source:
        evidence = _evidence()

        async def observe(self, **kwargs):
            return self.evidence

    source = Source()
    analyzer = ResourceAvailabilityAnalyzer(
        resource_kind="virtual_machine",
        resource_type="compute.vm",
        scope_ref=SCOPE,
        source=source,
        policy=_policy(),
        wall_clock=lambda: NOW,
    )
    (fault,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    source.evidence = _evidence(
        state=RUNNING,
        observed_at=NOW if fresh else fault.occurred_at,
    )
    (recovery,) = await analyzer.analyze_recovery(
        prior_finding=fault, finding_ref="finding:example", window_seconds=300
    )
    assert recovery.assessment.recovery_closed is fresh
    assert "finding:example" in recovery.evidence_refs


@pytest.mark.parametrize(
    "changes",
    [
        {"synthetic": True},
        {"conflicts": ("equal_time_conflict",)},
        {"completeness": 0.5},
        {"lane": StateFactLane.DESIRED, "authority": StateFactAuthority.APPROVED_POLICY},
        {
            "evidence_cutoff": NOW + timedelta(seconds=1),
            "recorded_at": NOW + timedelta(seconds=1),
        },
    ],
)
def test_canonical_state_metadata_must_be_observed_complete_and_uncontested(changes) -> None:
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="example-snapshot",
        effective_at=NOW - timedelta(seconds=30),
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory:example-snapshot:state",),
    )
    result = _assess(_evidence(state_metadata=replace(metadata, **changes)))
    assert result.status == "state_observation_unverified"
    assert result.recovery_closed is None
