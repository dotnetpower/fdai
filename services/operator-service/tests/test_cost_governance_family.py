"""Focused Cost Governance access, activation, and disclosure route tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.cost_governance import (
    CostAccessDecision,
    CostActivationSnapshot,
    CostGovernanceFamilyDependencies,
    build_cost_governance_routes,
    decode_cost_pseudonym_key,
)
from fdai_operator_service.families.cost_governance.contracts import (
    CostAnalyticsSnapshot,
    CostDisclosureAuditRecord,
    CostProjectionEvidenceSnapshot,
)
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAccessGrant,
    CostAmountPrecision,
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsRecommendation,
    CostAnalyticsRunReceipt,
    CostAnalyticsRunStatus,
    CostAnalyticsTrendPoint,
    CostDecisionCaseProjection,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostEvidenceSourceFacet,
    CostEvidenceState,
    CostGovernanceUnavailableReason,
    CostGranularity,
    CostIdentityVisibility,
    CostProjectionRecord,
    CostSettlementEffectProjection,
    CostSettlementOutcomeProjection,
    OperatorRole,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 8, 28, tzinfo=UTC)
ONTOLOGY_DIGEST = f"sha256:{'a' * 64}"


def _activation(
    *,
    available: bool = True,
    enabled: bool = True,
    reasons: tuple[str, ...] = (),
    revision: int = 4,
) -> CostActivationSnapshot:
    return CostActivationSnapshot(
        vertical_id="cost-governance",
        package_id="fdai-cost-governance",
        available=available,
        enabled=enabled,
        availability_reasons=reasons,
        package_version="0.1.0",
        image_digest=f"sha256:{'b' * 64}",
        asset_manifest_digest=f"sha256:{'c' * 64}",
        semantic_profile_digest=f"sha256:{'d' * 64}",
        ontology_release_digest=ONTOLOGY_DIGEST,
        revision=revision,
    )


HEADERS = {"Authorization": "Bearer token"}


def test_pseudonym_key_requires_persistent_256_bit_hexadecimal_material() -> None:
    assert decode_cost_pseudonym_key("ab" * 32) == bytes.fromhex("ab" * 32)
    assert decode_cost_pseudonym_key("") is None
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        decode_cost_pseudonym_key("not-a-key")
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        decode_cost_pseudonym_key("AB" * 32)
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        CostGovernanceFamilyDependencies(
            authenticator=object(),  # type: ignore[arg-type]
            access=object(),  # type: ignore[arg-type]
            activation=object(),  # type: ignore[arg-type]
            projections=object(),  # type: ignore[arg-type]
            pseudonym_key=b"short",
        )


class RecordingCostDependencies:
    """Record strict preflight and query ordering."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.audit_records: list[CostDisclosureAuditRecord] = []
        self.audit_failure = False
        self.access_allowed = True
        self.ceiling = DISCLOSURE_PRESETS["masked"]
        self.activation: CostActivationSnapshot | None = _activation()
        self.analytics_complete = True
        self.analytics_run_status = CostAnalyticsRunStatus.COMPLETE
        self.analytics_finished_at = NOW
        self.analytics_scope = "subscriptions/example"
        self.analytics_snapshot_id = f"analytics:{'d' * 64}"
        self.run_snapshot_id: str | None = self.analytics_snapshot_id
        self.case_items: tuple[CostDecisionCaseProjection, ...] = ()
        self.outcome_items: tuple[CostSettlementOutcomeProjection, ...] = ()
        self.reported_observation_count = 1
        self.reported_case_count: int | None = None
        self.reported_settlement_count: int | None = None
        self.read_scopes: list[str] = []

    async def read_access(self, **_: object) -> CostAccessDecision:
        self.calls.append("access")
        if not self.access_allowed:
            return CostAccessDecision(
                None,
                None,
                CostGovernanceUnavailableReason.ACCESS_GRANT_MISSING,
            )
        return CostAccessDecision(
            CostAccessGrant(
                grant_id="grant-1",
                principal_id="reader-id",
                revision=2,
                purpose="cost-governance-review",
                scopes=("*",),
                disclosure=DISCLOSURE_PRESETS["detailed"],
                effective_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=1),
                source_authority="operator-access-store",
            ),
            CostDisclosureCeiling(
                revision=3,
                disclosure=self.ceiling,
                effective_at=NOW - timedelta(days=1),
                source_authority="deployment-policy",
            ),
        )

    async def read_activation(self, package_id: str) -> CostActivationSnapshot | None:
        assert package_id == "cost-governance"
        self.calls.append("activation")
        return self.activation

    async def set_enabled(
        self,
        *,
        package_id: str,
        actor_id: str,
        enabled: bool,
        expected_revision: int,
        request_id: str,
    ) -> CostActivationSnapshot:
        assert package_id == "cost-governance"
        assert actor_id == "reader-id"
        assert request_id == "request-1234"
        self.calls.append("set-enabled")
        if self.activation is None or self.activation.revision != expected_revision:
            raise ValueError("Cost Governance activation revision conflict")
        self.activation = _activation(
            available=self.activation.available,
            enabled=enabled,
            reasons=self.activation.availability_reasons,
            revision=expected_revision + 1,
        )
        return self.activation

    async def read_records(self, **kwargs: object) -> tuple[CostProjectionRecord, ...]:
        self.calls.append("projection")
        self.read_scopes.append(str(kwargs["scope"]))
        return (
            CostProjectionRecord(
                record_id="costobs:1",
                group_id="compute",
                resource_id="resource/private",
                service_id="compute",
                amount=Decimal("120"),
                previous_amount=Decimal("100"),
                currency="USD",
                observed_at=NOW,
                completeness=Decimal("1"),
                source_authority="azure-cost-management",
                provenance_digest=f"sha256:{'a' * 64}",
            ),
        )

    async def read_analytics(self, *, scope: str) -> CostAnalyticsSnapshot | None:
        assert scope == "*"
        self.calls.append("analytics")
        return CostAnalyticsSnapshot(
            snapshot_id=self.analytics_snapshot_id,
            scope_id=self.analytics_scope,
            projection=CostAnalyticsProjection(
                source_authority="azure-cost-analytics",
                observed_at=NOW,
                complete=self.analytics_complete,
                trend=(
                    CostAnalyticsTrendPoint(
                        observed_on=date(2026, 8, 28),
                        amount=Decimal("120"),
                        currency="USD",
                        completeness=Decimal("1"),
                    ),
                ),
                budgets=(
                    CostAnalyticsBudget(
                        budget_ref="budget:0123456789abcdef",
                        amount=Decimal("49"),
                        current_spend=Decimal("20"),
                        currency="USD",
                        time_grain="Monthly",
                    ),
                ),
                recommendations=(
                    CostAnalyticsRecommendation(
                        recommendation_ref="recommendation:0123456789abcdef",
                        resource_ref="resource:0123456789abcdef",
                        resource_type="microsoft.compute/virtualmachines",
                        problem="Oversized virtual machine",
                        solution="Use a smaller compatible SKU",
                        impact="Medium",
                        monthly_savings=Decimal("20"),
                        currency="USD",
                        current_sku="Standard_D4s_v5",
                        target_sku="Standard_D2s_v5",
                        utilization_percent=Decimal("18"),
                        utilization_metric="cpu.percent.p95",
                        observed_at=NOW,
                        source_authority="azure-advisor",
                    ),
                ),
            ),
        )

    async def read_projection_evidence(
        self,
        *,
        scope: str,
        analytics_snapshot_id: str | None,
    ) -> CostProjectionEvidenceSnapshot:
        self.read_scopes.append(scope)
        assert analytics_snapshot_id in {None, self.analytics_snapshot_id}
        self.calls.append("evidence")
        source = CostEvidenceSourceFacet(
            source_authority="azure-cost-management",
            state=CostEvidenceState.COMPLETE,
            window_start_at=NOW - timedelta(days=1),
            window_end_at=NOW,
            latest_source_at=NOW,
            complete_count=self.reported_observation_count,
        )
        receipt = CostAnalyticsRunReceipt(
            run_id=f"costrun:{'f' * 64}",
            receipt_digest=f"sha256:{'f' * 64}",
            scope_digest=f"sha256:{'e' * 64}",
            venue="local",
            window_start_at=NOW - timedelta(days=1),
            window_end_at=NOW,
            started_at=self.analytics_finished_at - timedelta(minutes=1),
            finished_at=self.analytics_finished_at,
            status=self.analytics_run_status,
            sources=(source,),
            observation_count=1,
            failure_reason=(
                "provider_unavailable"
                if self.analytics_run_status is CostAnalyticsRunStatus.FAILED
                else None
            ),
            snapshot_id=(
                None
                if self.analytics_run_status
                in {CostAnalyticsRunStatus.FAILED, CostAnalyticsRunStatus.DISABLED}
                else self.run_snapshot_id
            ),
        )
        return CostProjectionEvidenceSnapshot(
            window_start_at=NOW - timedelta(days=1),
            window_end_at=NOW,
            latest_source_at=NOW,
            complete_count=self.reported_observation_count,
            partial_count=0,
            sources=(source,),
            latest_analytics_run=receipt,
            resource_candidate_count=0,
            incomplete_candidate_count=0,
            decision_case_count=(
                len(self.case_items)
                if self.reported_case_count is None
                else self.reported_case_count
            ),
            incomplete_decision_case_count=0,
            settlement_count=(
                len(self.outcome_items)
                if self.reported_settlement_count is None
                else self.reported_settlement_count
            ),
            incomplete_settlement_count=0,
        )

    async def read_decision_cases(self, **kwargs: object) -> tuple[CostDecisionCaseProjection, ...]:
        self.calls.append("decision-cases")
        self.read_scopes.append(str(kwargs["scope"]))
        return self.case_items

    async def read_settlement_outcomes(
        self, **kwargs: object
    ) -> tuple[CostSettlementOutcomeProjection, ...]:
        self.calls.append("settlements")
        self.read_scopes.append(str(kwargs["scope"]))
        return self.outcome_items

    async def append_disclosure_audit(self, record: CostDisclosureAuditRecord) -> None:
        if self.audit_failure:
            raise RuntimeError("audit unavailable")
        self.audit_records.append(record)


def _client(
    dependencies: RecordingCostDependencies,
    *,
    role: OperatorRole = OperatorRole.READER,
    authenticated_review_access: bool = False,
    include_analytics: bool = False,
) -> TestClient:
    authenticator = OperatorAuthenticator(
        verifier=lambda token: {
            "oid": "reader-id",
            "idtyp": "user",
            "roles": [role.value],
        },
        group_ids={},
    )
    return TestClient(
        Starlette(
            routes=build_cost_governance_routes(
                CostGovernanceFamilyDependencies(
                    authenticator=authenticator,
                    access=dependencies,
                    activation=dependencies,
                    projections=dependencies,
                    analytics=dependencies if include_analytics else None,
                    activation_writer=dependencies,
                    disclosure_audit=dependencies,
                    pseudonym_key=bytes(range(32)),
                    authenticated_review_access=authenticated_review_access,
                    clock=lambda: NOW,
                )
            )
        )
    )


def test_authentication_precedes_all_cost_reads() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies).get("/cost-governance/overview")
    assert response.status_code == 401
    assert dependencies.calls == []


def test_missing_user_grant_returns_403_without_activation_or_cost_query() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.access_allowed = False
    response = _client(dependencies).get("/cost-governance/overview", headers=HEADERS)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "access_grant_missing"
    assert dependencies.calls == ["access"]


@pytest.mark.parametrize(
    ("activation", "reason"),
    [
        (None, "package_absent"),
        (
            _activation(
                available=False,
                enabled=False,
                reasons=("host_incompatible",),
            ),
            "host_incompatible",
        ),
        (
            _activation(
                available=False,
                enabled=False,
                reasons=("missing_provider:cost-estimator",),
            ),
            "missing_provider",
        ),
    ],
)
def test_unavailable_activation_returns_404_without_cost_query(
    activation: CostActivationSnapshot | None,
    reason: str,
) -> None:
    dependencies = RecordingCostDependencies()
    dependencies.activation = activation
    response = _client(dependencies).get("/cost-governance/overview", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == reason
    assert dependencies.calls == ["access", "activation"]


def test_available_but_disabled_is_not_reported_as_unavailable() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.activation = _activation(available=True, enabled=False)

    availability = _client(dependencies).get(
        "/cost-governance/availability",
        headers=HEADERS,
    )
    assert availability.status_code == 200
    assert availability.json()["available"] is True
    assert availability.json()["enabled"] is False
    assert availability.json()["availability_reasons"] == []
    assert dependencies.calls == ["access", "activation"]

    dependencies.calls.clear()
    projection = _client(dependencies).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )
    assert projection.status_code == 404
    assert projection.json()["error"]["code"] == "package_disabled"
    assert dependencies.calls == ["access", "activation"]


def test_settings_are_discoverable_without_cost_data_access() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.access_allowed = False

    response = _client(dependencies).get("/cost-governance/settings", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["enabled"] is True
    assert response.json()["can_manage"] is False
    assert dependencies.calls == ["activation"]


def test_configured_authenticated_review_policy_grants_only_aggregate_read_access() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.access_allowed = False

    response = _client(
        dependencies,
        authenticated_review_access=True,
    ).get("/cost-governance/overview", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["disclosure"]["granularity"] == "group"
    assert response.json()["disclosure"]["identity_visibility"] == "none"
    assert response.json()["disclosure"]["amount_precision"] == "rounded"
    assert dependencies.calls == ["access", "activation", "projection", "evidence"]


def test_owner_can_change_activation_with_exact_revision() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies, role=OperatorRole.OWNER).put(
        "/cost-governance/settings",
        headers=HEADERS,
        json={
            "enabled": False,
            "expected_revision": 4,
            "request_id": "request-1234",
        },
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["activation_revision"] == 5
    assert dependencies.calls == ["activation", "set-enabled"]


def test_reader_cannot_change_activation() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies).put(
        "/cost-governance/settings",
        headers=HEADERS,
        json={
            "enabled": False,
            "expected_revision": 4,
            "request_id": "request-1234",
        },
    )

    assert response.status_code == 403
    assert dependencies.calls == ["activation"]


def test_unavailable_preflight_projects_persisted_reason_and_attribution() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.activation = _activation(
        available=False,
        enabled=False,
        reasons=("ontology_incompatible",),
    )

    response = _client(dependencies).get(
        "/cost-governance/availability",
        headers=HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["available"] is False
    assert response.json()["enabled"] is False
    assert response.json()["reason"] == "ontology_incompatible"
    assert response.json()["availability_reasons"] == ["ontology_incompatible"]
    assert response.json()["semantic_profile_digest"] == f"sha256:{'d' * 64}"
    assert dependencies.calls == ["access", "activation"]


def test_enabled_route_applies_policy_meet_before_serialization() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/resource-efficiency",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert dependencies.calls == [
        "access",
        "activation",
        "analytics",
        "projection",
        "evidence",
    ]
    item = response.json()["items"][0]
    assert response.json()["resource_efficiency_mode"] == "resource_candidate"
    assert item["kind"] == "resource_candidate"
    assert item["resource"].startswith("resource:")
    assert item["resource"] != "resource:0123456789abcdef"
    assert "projected_monthly_savings" not in item
    assert len(dependencies.audit_records) == 1
    audit = dependencies.audit_records[0]
    assert audit.record_count == 1
    assert audit.surface == "resource-efficiency"
    assert "reader-id" not in repr(audit)
    assert "resource/private" not in repr(audit)


def test_disclosure_audit_failure_blocks_cost_response() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.audit_failure = True

    response = _client(dependencies).get(
        "/cost-governance/resource-efficiency",
        headers=HEADERS,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "disclosure_audit_unavailable"
    assert dependencies.calls == ["access", "activation", "projection", "evidence"]
    assert dependencies.audit_records == []


def test_enabled_route_includes_disclosure_safe_analytics() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["detailed"]
    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["analytics"]["trend"][0]["amount"] == "120"
    evidence = response.json()["evidence"]
    assert evidence["window_start_at"] == "2026-08-27T00:00:00Z"
    assert evidence["freshness"] == "fresh"
    assert evidence["complete_count"] == 1
    assert evidence["disclosure"]["amount_precision"] == "exact"
    assert {item["surface"] for item in evidence["readiness"]} == {
        "observations",
        "analytics",
        "resource-candidates",
        "decision-cases",
        "settlements",
    }
    assert dependencies.calls == [
        "access",
        "activation",
        "analytics",
        "projection",
        "evidence",
    ]


def test_analytics_amounts_follow_the_effective_disclosure_policy() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["analytics"]["trend"] == []
    assert "analytics_amount_suppressed" in response.json()["analytics"]["limitations"]


def test_group_disclosure_suppresses_resource_advisor_details() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["aggregate"]

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    analytics = response.json()["analytics"]
    assert analytics["recommendations"] == []
    assert "analytics_recommendations_suppressed" in analytics["limitations"]
    assert "Oversized virtual machine" not in response.text
    assert "Standard_D4s_v5" not in response.text


def test_small_positive_budget_is_suppressed_instead_of_rounded_to_zero() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = CostDisclosurePolicy(
        granularity=CostGranularity.GROUP,
        identity_visibility=CostIdentityVisibility.NONE,
        amount_precision=CostAmountPrecision.ROUNDED,
        rounding_increment=Decimal("100"),
    )

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["analytics"]["budgets"] == []
    assert response.json()["analytics"]["recommendations"] == []
    assert "analytics_amount_suppressed" in response.json()["analytics"]["limitations"]
    assert "analytics_recommendations_suppressed" in response.json()["analytics"]["limitations"]


def test_hidden_partial_analytics_still_lowers_projection_completeness() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["hidden"]
    dependencies.analytics_complete = False
    dependencies.analytics_run_status = CostAnalyticsRunStatus.PARTIAL

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert "analytics" not in response.json()
    assert response.json()["complete"] is False
    analytics_readiness = next(
        item for item in response.json()["evidence"]["readiness"] if item["surface"] == "analytics"
    )
    assert analytics_readiness["state"] == "partial"
    assert analytics_readiness["reason"] == "analytics_run_partial"
    assert not {"approval", "execution", "promotion"} & set(response.json())


@pytest.mark.parametrize(
    ("status", "finished_at", "reason"),
    [
        (CostAnalyticsRunStatus.FAILED, NOW, "analytics_run_failed"),
        (CostAnalyticsRunStatus.COMPLETE, NOW - timedelta(days=3), "analytics_stale"),
    ],
)
def test_failed_or_stale_analytics_is_explicitly_unavailable(
    status: CostAnalyticsRunStatus,
    finished_at: datetime,
    reason: str,
) -> None:
    dependencies = RecordingCostDependencies()
    dependencies.analytics_run_status = status
    dependencies.analytics_finished_at = finished_at

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    analytics_readiness = next(
        item for item in response.json()["evidence"]["readiness"] if item["surface"] == "analytics"
    )
    assert analytics_readiness == {
        "surface": "analytics",
        "state": "unavailable",
        "reason": reason,
        "record_count": 1,
        "returned_count": 1,
        "truncated": False,
        "latest_evidence_at": finished_at.isoformat().replace("+00:00", "Z"),
    }
    assert response.json()["complete"] is False


def test_observation_mode_case_and_settlement_are_read_from_owned_lineage() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["detailed"]
    dependencies.case_items = (
        CostDecisionCaseProjection(
            case_ref=f"case:{'1' * 24}",
            revision=2,
            target_refs=(f"resource:{'2' * 24}",),
            evidence_cutoff=NOW - timedelta(hours=1),
            decision_frame_digest=f"sha256:{'3' * 64}",
            option_ids=("option.no-action",),
            selected_option_id="option.no-action",
            verdict="hold",
            reason="hard_dependency_observation_mode",
            evidence_refs=("evidence:one",),
            evidence_sources=("heimdall",),
            recovery_steps=("reacquire-context:success",),
            recorded_at=NOW,
            source_authority="forseti-observation-mode",
        ),
    )
    dependencies.outcome_items = (
        CostSettlementOutcomeProjection(
            case_ref=f"case:{'1' * 24}",
            revision=2,
            action_ref="action-run:one",
            action_revision=3,
            decision_frame_digest=f"sha256:{'3' * 64}",
            terminal=True,
            verified_savings=Decimal("20"),
            currency="USD",
            rollback_requested=False,
            recovery_observed=False,
            effects=(
                CostSettlementEffectProjection(
                    effect_id="effect-cost",
                    kind="cost",
                    status="verified",
                    reason="expected_effect_observed",
                    terminal=True,
                    observation_digest=f"sha256:{'4' * 64}",
                    completeness_digest=f"sha256:{'5' * 64}",
                ),
            ),
            settled_at=NOW,
        ),
    )

    cases = _client(dependencies).get(
        "/cost-governance/optimization-cases",
        headers=HEADERS,
    )
    assert cases.status_code == 200
    assert cases.json()["items"][0]["kind"] == "decision_case"
    assert cases.json()["items"][0]["verdict"] == "hold"
    assert dependencies.calls == [
        "access",
        "activation",
        "evidence",
        "decision-cases",
    ]

    dependencies.calls.clear()
    outcomes = _client(dependencies).get(
        "/cost-governance/outcomes",
        headers=HEADERS,
    )
    assert outcomes.status_code == 200
    assert outcomes.json()["items"][0]["kind"] == "settlement_outcome"
    assert outcomes.json()["items"][0]["verified_savings"] == "20"
    assert dependencies.calls == [
        "access",
        "activation",
        "evidence",
        "settlements",
    ]


def test_wildcard_reads_bind_every_projection_to_returned_analytics_scope() -> None:
    dependencies = RecordingCostDependencies()

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert dependencies.read_scopes == [
        "subscriptions/example",
        "subscriptions/example",
    ]
    analytics_readiness = next(
        item for item in response.json()["evidence"]["readiness"] if item["surface"] == "analytics"
    )
    assert analytics_readiness["state"] == "complete"


def test_missing_wildcard_analytics_snapshot_cannot_report_complete() -> None:
    response = _client(RecordingCostDependencies()).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    readiness = next(
        item for item in response.json()["evidence"]["readiness"] if item["surface"] == "analytics"
    )
    assert readiness["state"] == "unavailable"
    assert readiness["reason"] == "analytics_snapshot_missing"
    assert response.json()["complete"] is False


def test_wildcard_readiness_rejects_a_run_for_another_snapshot() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.run_snapshot_id = f"analytics:{'e' * 64}"

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    readiness = next(
        item for item in response.json()["evidence"]["readiness"] if item["surface"] == "analytics"
    )
    assert readiness["state"] == "unavailable"
    assert readiness["reason"] == "analytics_snapshot_missing"
    assert response.json()["complete"] is False


def test_projection_limit_marks_observation_totals_partial() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.reported_observation_count = 2

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview?limit=1",
        headers=HEADERS,
    )

    readiness = next(
        item
        for item in response.json()["evidence"]["readiness"]
        if item["surface"] == "observations"
    )
    assert readiness["record_count"] == 2
    assert readiness["returned_count"] == 1
    assert readiness["truncated"] is True
    assert readiness["reason"] == "projection_truncated"
    assert response.json()["complete"] is False


@pytest.mark.parametrize(
    ("route", "count_attribute", "readiness_surface"),
    [
        ("/cost-governance/optimization-cases?limit=1", "reported_case_count", "decision-cases"),
        ("/cost-governance/outcomes?limit=1", "reported_settlement_count", "settlements"),
    ],
)
def test_projection_limit_marks_lineage_partial(
    route: str,
    count_attribute: str,
    readiness_surface: str,
) -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["detailed"]
    dependencies.case_items = (
        CostDecisionCaseProjection(
            case_ref=f"case:{'1' * 24}",
            revision=1,
            target_refs=(f"resource:{'2' * 24}",),
            evidence_cutoff=NOW - timedelta(hours=1),
            decision_frame_digest=f"sha256:{'3' * 64}",
            option_ids=("option.no-action",),
            verdict="hold",
            reason="hard_dependency_observation_mode",
            evidence_refs=("evidence:one",),
            evidence_sources=("heimdall",),
            recorded_at=NOW,
            source_authority="forseti-observation-mode",
        ),
    )
    dependencies.outcome_items = (
        CostSettlementOutcomeProjection(
            case_ref=f"case:{'1' * 24}",
            revision=1,
            action_ref="action-run:one",
            action_revision=1,
            decision_frame_digest=f"sha256:{'3' * 64}",
            terminal=False,
            rollback_requested=True,
            recovery_observed=False,
            effects=(
                CostSettlementEffectProjection(
                    effect_id="effect-cost",
                    kind="cost",
                    status="failed",
                    reason="expected_effect_failed",
                    terminal=True,
                    observation_digest=f"sha256:{'4' * 64}",
                    completeness_digest=f"sha256:{'5' * 64}",
                ),
            ),
            settled_at=NOW,
        ),
    )
    setattr(dependencies, count_attribute, 2)

    response = _client(dependencies).get(route, headers=HEADERS)

    readiness = next(
        item
        for item in response.json()["evidence"]["readiness"]
        if item["surface"] == readiness_surface
    )
    assert readiness["record_count"] == 2
    assert readiness["returned_count"] == 1
    assert readiness["truncated"] is True
    assert readiness["reason"] == "projection_truncated"
    assert response.json()["complete"] is False


@pytest.mark.parametrize(
    ("route", "kind"),
    [
        ("/cost-governance/overview", "trend"),
        ("/cost-governance/resource-efficiency", "summary"),
        ("/cost-governance/optimization-cases", None),
        ("/cost-governance/outcomes", None),
    ],
)
def test_each_surface_returns_only_authoritative_typed_projection(
    route: str,
    kind: str | None,
) -> None:
    response = _client(RecordingCostDependencies()).get(route, headers=HEADERS)
    assert response.status_code == 200
    if kind is None:
        assert response.json()["items"] == []
    else:
        assert response.json()["items"][0]["kind"] == kind


def test_availability_preflight_never_queries_cost_table() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies).get(
        "/cost-governance/availability",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["enabled"] is True
    assert response.json()["package_version"] == "0.1.0"
    assert response.json()["ontology_release_digest"] == ONTOLOGY_DIGEST
    assert dependencies.calls == ["access", "activation"]


def test_hidden_effective_disclosure_returns_metadata_without_cost_query() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["hidden"]

    response = _client(dependencies).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["complete"] is False
    assert response.json()["suppressed_count"] == 0
    assert dependencies.calls == ["access", "activation", "evidence"]


def test_finops_is_n_minus_one_alias_for_overview() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies).get("/finops", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    assert response.json()["surface"] == "overview"
