from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fdai_cost_governance import (
    FinOpsActionKind,
    FinOpsEnvironment,
    OptimizationDisposition,
    ResourceContext,
    ResourceOptimizationEvidence,
    ResourceOptimizationPlanner,
    ServiceFamilyProfile,
)

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)


def _profile(*resource_types: str) -> ServiceFamilyProfile:
    return ServiceFamilyProfile(
        profile_id="compute-conservative",
        version="1.0.0",
        resource_types=frozenset(resource_types or ("virtual-machine",)),
        minimum_samples=24,
        maximum_evidence_age=timedelta(hours=2),
        maximum_utilization_p95=Decimal("0.4"),
        minimum_headroom=Decimal("0.3"),
        minimum_capacity=1,
    )


def _evidence(
    *,
    resource_type: str = "virtual-machine",
    proposed_kind: FinOpsActionKind = FinOpsActionKind.RIGHT_SIZE,
    proposed_capacity: int | None = 2,
    observed_at: datetime = NOW - timedelta(minutes=5),
    completeness: Decimal = Decimal("1"),
    utilization: Decimal = Decimal("0.2"),
    headroom: Decimal = Decimal("0.5"),
    dependents: tuple[str, ...] = (),
) -> ResourceOptimizationEvidence:
    return ResourceOptimizationEvidence(
        resource=ResourceContext(
            resource_id="resource-a",
            environment=FinOpsEnvironment.DEV,
            current_capacity=4,
            dependent_ids=dependents,
        ),
        resource_type=resource_type,
        observed_at=observed_at,
        source_authority="cost-analytics:verified",
        completeness=completeness,
        sample_count=48,
        utilization_p95=utilization,
        headroom=headroom,
        proposed_kind=proposed_kind,
        proposed_capacity=proposed_capacity,
    )


def test_right_size_candidate_pins_profile_and_grants_no_authority() -> None:
    profile = _profile("virtual-machine")
    result = ResourceOptimizationPlanner(profiles=(profile,)).plan(_evidence(), now=NOW)

    assert result.disposition is OptimizationDisposition.CANDIDATE
    assert result.profile_id == profile.profile_id
    assert result.profile_version == profile.version
    assert result.profile_digest == profile.digest
    assert result.candidate is not None
    assert result.candidate.target_capacity == 2
    assert result.execution_authority is False


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (_evidence(resource_type="unsupported"), "service_family_profile_unavailable"),
        (_evidence(completeness=Decimal("0.5")), "evidence_incomplete"),
        (_evidence(observed_at=NOW - timedelta(hours=3)), "evidence_stale"),
    ],
)
def test_missing_or_unqualified_evidence_requires_review(
    evidence: ResourceOptimizationEvidence,
    reason: str,
) -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(evidence, now=NOW)

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.candidate is None
    assert result.reasons == (reason,)


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (_evidence(observed_at=NOW + timedelta(minutes=1)), "evidence_from_future"),
        (
            _evidence(proposed_kind=FinOpsActionKind.AUTOSCALE_ADJUST),
            "unsupported_optimization_kind",
        ),
    ],
)
def test_untrusted_or_unsupported_advice_requires_review(
    evidence: ResourceOptimizationEvidence,
    reason: str,
) -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(evidence, now=NOW)

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.execution_authority is False
    assert result.reasons == (reason,)


def test_high_utilization_keeps_current_capacity() -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(
        _evidence(utilization=Decimal("0.6")),
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.KEEP
    assert result.reasons == ("utilization_requires_current_capacity",)


def test_shutdown_with_dependents_requires_review() -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(
        _evidence(
            proposed_kind=FinOpsActionKind.SHUTDOWN,
            proposed_capacity=None,
            utilization=Decimal("0"),
            dependents=("dependent-a",),
        ),
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.reasons == ("shutdown_would_strand_dependents:count=1",)


def test_shutdown_candidate_requires_zero_utilization_and_no_dependents() -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(
        _evidence(
            proposed_kind=FinOpsActionKind.SHUTDOWN,
            proposed_capacity=None,
            utilization=Decimal("0"),
        ),
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.CANDIDATE
    assert result.candidate is not None
    assert result.candidate.kind is FinOpsActionKind.SHUTDOWN
    assert result.execution_authority is False


def test_nonzero_utilization_never_becomes_shutdown_candidate() -> None:
    result = ResourceOptimizationPlanner(profiles=(_profile(),)).plan(
        _evidence(
            proposed_kind=FinOpsActionKind.SHUTDOWN,
            proposed_capacity=None,
            utilization=Decimal("0.0000000001"),
        ),
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.reasons == ("shutdown_requires_zero_utilization",)


def test_planning_rejects_naive_evaluation_time() -> None:
    with pytest.raises(ValueError, match="time MUST be timezone-aware"):
        ResourceOptimizationPlanner(profiles=(_profile(),)).plan(
            _evidence(),
            now=datetime(2026, 10, 15, 10),
        )


def test_profile_registry_rejects_ambiguous_resource_type() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ResourceOptimizationPlanner(
            profiles=(
                _profile("virtual-machine"),
                ServiceFamilyProfile(
                    profile_id="compute-other",
                    version="1.0.0",
                    resource_types=frozenset({"virtual-machine"}),
                    minimum_samples=12,
                    maximum_evidence_age=timedelta(hours=1),
                    maximum_utilization_p95=Decimal("0.3"),
                    minimum_headroom=Decimal("0.2"),
                ),
            )
        )


def test_evidence_rejects_empty_target_identity() -> None:
    evidence = _evidence()

    with pytest.raises(ValueError, match="identity MUST be non-empty"):
        ResourceOptimizationEvidence(
            resource=ResourceContext(
                resource_id="",
                environment=evidence.resource.environment,
                current_capacity=evidence.resource.current_capacity,
            ),
            resource_type=evidence.resource_type,
            observed_at=evidence.observed_at,
            source_authority=evidence.source_authority,
            completeness=evidence.completeness,
            sample_count=evidence.sample_count,
            utilization_p95=evidence.utilization_p95,
            headroom=evidence.headroom,
            proposed_kind=evidence.proposed_kind,
            proposed_capacity=evidence.proposed_capacity,
        )


@pytest.mark.parametrize("ratio", [Decimal("NaN"), Decimal("Infinity")])
def test_profile_rejects_non_finite_ratio(ratio: Decimal) -> None:
    with pytest.raises(ValueError, match="finite ratio"):
        ServiceFamilyProfile(
            profile_id="compute-invalid",
            version="1.0.0",
            resource_types=frozenset({"virtual-machine"}),
            minimum_samples=1,
            maximum_evidence_age=timedelta(hours=1),
            maximum_utilization_p95=ratio,
            minimum_headroom=Decimal("0.2"),
        )
