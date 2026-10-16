from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fdai_cost_governance import (
    ClarificationDisposition,
    ClarificationResponseShape,
    CoupledResourceOptimizationEvidence,
    FinOpsActionKind,
    FinOpsEnvironment,
    OptimizationClarificationAttestation,
    OptimizationDisposition,
    ResourceContext,
    ResourceOptimizationEvidence,
    ResourceOptimizationPlanner,
    ServiceFamilyProfile,
    build_optimization_clarification,
    default_service_family_profiles,
    evaluate_optimization_attestation,
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
    sample_count: int = 48,
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
        sample_count=sample_count,
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
    assert not hasattr(result, "execution_authority")


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
    assert not hasattr(result, "execution_authority")
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
    assert not hasattr(result, "execution_authority")


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


def test_default_profiles_cover_the_five_reviewed_service_families() -> None:
    profiles = default_service_family_profiles()
    resource_types = {item for profile in profiles for item in profile.resource_types}

    assert len(profiles) == 5
    assert resource_types == {
        "virtual-machine",
        "virtual-machine-scale-set",
        "azure-sql",
        "postgresql",
        "aks-node-pool",
        "app-service",
        "container-app",
        "storage-account",
    }
    assert all(profile.required_metrics for profile in profiles)
    assert len({profile.digest for profile in profiles}) == 5


def test_default_profile_requires_complete_family_metrics() -> None:
    profile = default_service_family_profiles()[0]
    result = ResourceOptimizationPlanner(profiles=(profile,)).plan(
        _evidence(resource_type="virtual-machine", sample_count=200),
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.reasons[0].startswith("required_metrics_missing:")


def test_coupled_target_requires_complete_membership_and_tested_rollback() -> None:
    profile = _profile("virtual-machine")
    first = _evidence()
    second = replace(
        first,
        resource=ResourceContext(
            resource_id="resource-b",
            environment=FinOpsEnvironment.DEV,
            current_capacity=4,
        ),
    )
    evidence = CoupledResourceOptimizationEvidence(
        target_set_id="coupled-a",
        target_revision_digest="sha256:" + "a" * 64,
        resources=(first, second),
        causal_order=("resource-a", "resource-b"),
        membership_complete=False,
        truncated=True,
        rollback_tested=False,
        logical_target_lock="lock:coupled-a",
        idempotency_key="optimization:coupled-a:v1",
    )

    result = ResourceOptimizationPlanner(profiles=(profile,)).plan_coupled(
        evidence,
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.REVIEW_REQUIRED
    assert result.reasons == (
        "target_membership_incomplete",
        "target_membership_truncated",
        "coupled_rollback_untested",
    )
    assert not hasattr(result, "execution_authority")


def test_coupled_target_routes_complete_candidate_set_to_governed_path() -> None:
    profile = _profile("virtual-machine")
    first = _evidence()
    second = ResourceOptimizationEvidence(
        resource=ResourceContext(
            resource_id="resource-b",
            environment=FinOpsEnvironment.DEV,
            current_capacity=4,
        ),
        resource_type=first.resource_type,
        observed_at=first.observed_at,
        source_authority=first.source_authority,
        completeness=first.completeness,
        sample_count=first.sample_count,
        utilization_p95=first.utilization_p95,
        headroom=first.headroom,
        proposed_kind=first.proposed_kind,
        proposed_capacity=first.proposed_capacity,
    )
    evidence = CoupledResourceOptimizationEvidence(
        target_set_id="coupled-a",
        target_revision_digest="sha256:" + "a" * 64,
        resources=(first, second),
        causal_order=("resource-a", "resource-b"),
        membership_complete=True,
        truncated=False,
        rollback_tested=True,
        logical_target_lock="lock:coupled-a",
        idempotency_key="optimization:coupled-a:v1",
    )

    result = ResourceOptimizationPlanner(profiles=(profile,)).plan_coupled(
        evidence,
        now=NOW,
    )

    assert result.disposition is OptimizationDisposition.CANDIDATE
    assert len(result.candidates) == 2
    assert result.route == "risk_gate"
    assert result.approval_required is True
    assert not hasattr(result, "execution_authority")


def test_targeted_clarification_accepts_one_scoped_fact_without_authority() -> None:
    request = build_optimization_clarification(
        target_id="resource-a",
        target_revision_digest="sha256:" + "a" * 64,
        missing_fact="workload_priority",
        blocking_reason="workload_priority_unavailable",
        eligible_roles=("ServiceOwner",),
        response_shape=ClarificationResponseShape.CHOICE,
        allowed_values=("critical", "non-critical"),
        effective_scope="resource-a",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        reevaluation_key="decision-case-a:revision-1",
        recovery_evidence_refs=("recovery:graph", "recovery:provider"),
    )
    attestation = OptimizationClarificationAttestation(
        request_id=request.request_id,
        actor_id="operator-a",
        actor_role="ServiceOwner",
        response="non-critical",
        effective_scope="resource-a",
        recorded_at=NOW,
        effective_until=NOW + timedelta(minutes=30),
    )

    result = evaluate_optimization_attestation(request, attestation, now=NOW)

    assert result.disposition is ClarificationDisposition.ACCEPTED
    assert result.reevaluation_key == "decision-case-a:revision-1"
    assert result.accepted_value == "non-critical"
    assert not hasattr(result, "approval_authority")
    assert not hasattr(result, "execution_authority")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"authoritative_conflict": True}, "authoritative_evidence_conflict"),
        ({"now": NOW + timedelta(hours=2)}, "attestation_expired"),
    ],
)
def test_targeted_clarification_holds_conflict_or_expiry(
    kwargs: dict[str, object],
    reason: str,
) -> None:
    request = build_optimization_clarification(
        target_id="resource-a",
        target_revision_digest="sha256:" + "a" * 64,
        missing_fact="workload_priority",
        blocking_reason="workload_priority_unavailable",
        eligible_roles=("ServiceOwner",),
        response_shape=ClarificationResponseShape.BOOLEAN,
        effective_scope="resource-a",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        reevaluation_key="decision-case-a:revision-1",
        recovery_evidence_refs=("recovery:graph",),
    )
    attestation = OptimizationClarificationAttestation(
        request_id=request.request_id,
        actor_id="operator-a",
        actor_role="ServiceOwner",
        response="true",
        effective_scope="resource-a",
        recorded_at=NOW,
        effective_until=NOW + timedelta(minutes=30),
    )
    call_kwargs = {"now": NOW, **kwargs}

    result = evaluate_optimization_attestation(request, attestation, **call_kwargs)

    assert result.disposition is ClarificationDisposition.HELD
    assert result.reason == reason
    assert result.accepted_value is None
