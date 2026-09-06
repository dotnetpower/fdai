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
)
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAccessGrant,
    CostAmountPrecision,
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsTrendPoint,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostGovernanceUnavailableReason,
    CostGranularity,
    CostIdentityVisibility,
    CostProjectionRecord,
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


class RecordingCostDependencies:
    """Record strict preflight and query ordering."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.access_allowed = True
        self.ceiling = DISCLOSURE_PRESETS["masked"]
        self.activation: CostActivationSnapshot | None = _activation()
        self.analytics_complete = True

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

    async def read_records(self, **_: object) -> tuple[CostProjectionRecord, ...]:
        self.calls.append("projection")
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

    async def read_analytics(self, *, scope: str) -> CostAnalyticsProjection | None:
        assert scope == "*"
        self.calls.append("analytics")
        return CostAnalyticsProjection(
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
        )


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
    assert dependencies.calls == ["access", "activation", "projection"]


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
    response = _client(dependencies).get(
        "/cost-governance/resource-efficiency",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert dependencies.calls == ["access", "activation", "projection"]
    item = response.json()["items"][0]
    assert item["kind"] == "resource"
    assert item["resource"].startswith("resource:")
    assert item["resource"] != "resource/private"
    assert "amount_band" in item
    assert "amount_exact" not in item


def test_enabled_route_includes_disclosure_safe_analytics() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["detailed"]
    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["analytics"]["trend"][0]["amount"] == "120"
    assert dependencies.calls == ["access", "activation", "projection", "analytics"]


def test_analytics_amounts_follow_the_effective_disclosure_policy() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["analytics"]["trend"] == []
    assert "analytics_amount_suppressed" in response.json()["analytics"]["limitations"]


def test_small_budget_is_suppressed_instead_of_rounded_to_invalid_zero() -> None:
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


def test_hidden_partial_analytics_still_lowers_projection_completeness() -> None:
    dependencies = RecordingCostDependencies()
    dependencies.ceiling = DISCLOSURE_PRESETS["hidden"]
    dependencies.analytics_complete = False

    response = _client(dependencies, include_analytics=True).get(
        "/cost-governance/overview",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert "analytics" not in response.json()
    assert response.json()["complete"] is False
    assert not {"approval", "execution", "promotion"} & set(response.json())


@pytest.mark.parametrize(
    ("route", "kind"),
    [
        ("/cost-governance/overview", "trend"),
        ("/cost-governance/resource-efficiency", "resource"),
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
    assert response.json()["complete"] is True
    assert response.json()["suppressed_count"] == 0
    assert dependencies.calls == ["access", "activation"]


def test_finops_is_n_minus_one_alias_for_overview() -> None:
    dependencies = RecordingCostDependencies()
    response = _client(dependencies).get("/finops", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    assert response.json()["surface"] == "overview"
