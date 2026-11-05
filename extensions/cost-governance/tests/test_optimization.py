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
    assert not hasattr(result, "route")
    assert not hasattr(result, "approval_required")
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


def test_optimization_validation_and_planner_branches() -> None:
    from dataclasses import replace

    base_prof = _profile("virtual-machine")
    for prof_kwargs, match in (
        ({"profile_id": " "}, "identity MUST be non-empty"),
        ({"resource_types": frozenset({" "})}, "resource types MUST be non-empty"),
        ({"required_metrics": frozenset({" bad "})}, "metrics MUST be exact"),
        ({"minimum_samples": 0}, "evidence bounds MUST be positive"),
        ({"minimum_capacity": 0}, "minimum_capacity MUST be positive"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(base_prof, **prof_kwargs)

    base_ev = _evidence()
    for ev_kwargs, match in (
        ({"observed_at": datetime(2026, 9, 1)}, "timezone-aware"),
        ({"sample_count": -1}, "non-negative"),
        ({"proposed_capacity": -1}, "proposed_capacity MUST be non-negative"),
        (
            {"metrics": (("z", Decimal("1")), ("a", Decimal("1")))},
            "unique and sorted",
        ),
        ({"metrics": ((" bad ", Decimal("1")),)}, "exact and finite"),
        ({"incompatibilities": (" bad ",)}, "incompatibilities MUST be exact"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(base_ev, **ev_kwargs)

    second_ev = replace(
        base_ev,
        resource=ResourceContext(
            resource_id="resource-b",
            environment=FinOpsEnvironment.DEV,
            current_capacity=4,
        ),
    )
    base_coupled = CoupledResourceOptimizationEvidence(
        target_set_id="coupled-a",
        target_revision_digest="sha256:" + "a" * 64,
        resources=(base_ev, second_ev),
        causal_order=("resource-a", "resource-b"),
        membership_complete=True,
        truncated=False,
        rollback_tested=True,
        logical_target_lock="lock:coupled-a",
        idempotency_key="optimization:coupled-a:v1",
    )
    for c_kwargs, match in (
        ({"target_set_id": " "}, "identity MUST be exact"),
        ({"target_revision_digest": "bad"}, "SHA-256"),
        ({"resources": (base_ev,)}, "between 2 and 20"),
        ({"resources": (base_ev, base_ev)}, "resources MUST be unique"),
        ({"causal_order": ("resource-a",)}, "cover each resource once"),
        (
            {"causal_order": ("resource-a", "resource-b", "resource-a")},
            "causal order MUST be unique",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            replace(base_coupled, **c_kwargs)

    from fdai_cost_governance.optimization import OptimizationClarificationRequest

    base_req = build_optimization_clarification(
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
        recovery_evidence_refs=("recovery:graph",),
    )
    for r_kwargs, match in (
        ({"request_id": " "}, "identity MUST be exact"),
        ({"created_at": datetime(2026, 9, 1)}, "timezone-aware"),
        ({"expires_at": NOW}, "expiry MUST follow creation"),
        ({"eligible_roles": ()}, "non-empty and exact"),
        ({"eligible_roles": ("A", "A")}, "bounds MUST be unique"),
        ({"allowed_values": (" bad ",)}, "allowed values MUST be exact"),
        ({"allowed_values": ("a", "a")}, "allowed values MUST be unique"),
        ({"allowed_values": ()}, "choice clarification MUST declare allowed values"),
        (
            {"response_shape": ClarificationResponseShape.BOOLEAN},
            "non-choice clarification MUST NOT declare allowed values",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            OptimizationClarificationRequest(
                **{
                    "request_id": base_req.request_id,
                    "target_id": base_req.target_id,
                    "target_revision_digest": base_req.target_revision_digest,
                    "missing_fact": base_req.missing_fact,
                    "blocking_reason": base_req.blocking_reason,
                    "eligible_roles": base_req.eligible_roles,
                    "response_shape": base_req.response_shape,
                    "allowed_values": base_req.allowed_values,
                    "effective_scope": base_req.effective_scope,
                    "created_at": base_req.created_at,
                    "expires_at": base_req.expires_at,
                    "reevaluation_key": base_req.reevaluation_key,
                    "recovery_evidence_refs": base_req.recovery_evidence_refs,
                    **r_kwargs,
                }
            )

    base_att = OptimizationClarificationAttestation(
        request_id=base_req.request_id,
        actor_id="operator-a",
        actor_role="ServiceOwner",
        response="non-critical",
        effective_scope="resource-a",
        recorded_at=NOW,
        effective_until=NOW + timedelta(minutes=30),
    )
    for a_kwargs, match in (
        ({"actor_id": " "}, "fields MUST be exact"),
        ({"response": "x" * 513}, "too long"),
        ({"recorded_at": datetime(2026, 9, 1)}, "timezone-aware"),
        ({"effective_until": NOW - timedelta(seconds=1)}, "interval is invalid"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(base_att, **a_kwargs)

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_optimization_attestation(base_req, base_att, now=datetime(2026, 9, 1))
    assert (
        evaluate_optimization_attestation(
            base_req, replace(base_att, request_id="other"), now=NOW
        ).reason
        == "request_identity_mismatch"
    )
    assert (
        evaluate_optimization_attestation(
            base_req,
            replace(base_att, recorded_at=NOW - timedelta(minutes=5)),
            now=NOW,
        ).reason
        == "attestation_time_invalid"
    )
    assert (
        evaluate_optimization_attestation(
            base_req, replace(base_att, actor_role="Other"), now=NOW
        ).reason
        == "respondent_role_ineligible"
    )
    assert (
        evaluate_optimization_attestation(
            base_req, replace(base_att, effective_scope="other"), now=NOW
        ).reason
        == "attestation_scope_mismatch"
    )
    assert (
        evaluate_optimization_attestation(
            base_req, replace(base_att, response="bad"), now=NOW
        ).reason
        == "attestation_response_invalid"
    )
    bool_req = replace(
        base_req,
        response_shape=ClarificationResponseShape.BOOLEAN,
        allowed_values=(),
    )
    assert (
        evaluate_optimization_attestation(
            bool_req, replace(base_att, response="maybe"), now=NOW
        ).reason
        == "attestation_response_invalid"
    )

    with pytest.raises(ValueError, match="at least one service family profile"):
        ResourceOptimizationPlanner(profiles=())

    planner = ResourceOptimizationPlanner(profiles=(replace(base_prof, minimum_capacity=2),))
    assert planner.plan(replace(base_ev, sample_count=1), now=NOW).reasons == (
        "sample_count_insufficient",
    )
    assert planner.plan(
        replace(base_ev, incompatibilities=("incompatible_sku",)), now=NOW
    ).reasons == ("incompatible_sku",)
    assert planner.plan(replace(base_ev, headroom=Decimal("0.01")), now=NOW).reasons == (
        "headroom_below_profile_floor",
    )
    assert planner.plan(replace(base_ev, proposed_capacity=None), now=NOW).reasons == (
        "target_capacity_required",
    )
    assert planner.plan(replace(base_ev, proposed_capacity=4), now=NOW).reasons == (
        "no_capacity_reduction",
    )
    assert planner.plan(replace(base_ev, proposed_capacity=1), now=NOW).reasons == (
        "target_below_profile_floor",
    )

    sub_scoped = replace(base_coupled, subscription_scoped=True)
    assert "subscription_scope_not_actionable" in planner.plan_coupled(sub_scoped, now=NOW).reasons

    rev_coupled = replace(base_coupled, resources=(replace(base_ev, sample_count=1), second_ev))
    assert (
        planner.plan_coupled(rev_coupled, now=NOW).disposition
        is OptimizationDisposition.REVIEW_REQUIRED
    )

    keep_ev1 = replace(base_ev, headroom=Decimal("0.01"))
    keep_ev2 = replace(second_ev, headroom=Decimal("0.01"))
    all_keep = planner.plan_coupled(
        replace(base_coupled, resources=(keep_ev1, keep_ev2)),
        now=NOW,
    )
    assert all_keep.disposition is OptimizationDisposition.KEEP

    mixed_keep = planner.plan_coupled(
        replace(base_coupled, resources=(keep_ev1, second_ev)),
        now=NOW,
    )
    assert mixed_keep.reasons == ("coupled_members_do_not_share_one_eligible_outcome",)
