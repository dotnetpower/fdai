"""Cost Governance service-contract and disclosure tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import product

import pytest
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAccessGrant,
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsRecommendation,
    CostAnalyticsTrendPoint,
    CostAmountPrecision,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostGovernanceAvailability,
    CostGovernanceProjection,
    CostGranularity,
    CostIdentityVisibility,
    CostProjectionRecord,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    disclose_cost_records,
)


def _record(**overrides: object) -> CostProjectionRecord:
    values: dict[str, object] = {
        "record_id": "costobs:1",
        "group_id": "production",
        "resource_id": "resource/private",
        "service_id": "compute",
        "amount": Decimal("1234.56"),
        "previous_amount": Decimal("1000"),
        "currency": "USD",
        "observed_at": datetime(2026, 8, 28, tzinfo=UTC),
        "completeness": Decimal("1"),
        "source_authority": "azure-cost-management",
        "provenance_digest": f"sha256:{'a' * 64}",
    }
    values.update(overrides)
    return CostProjectionRecord.model_validate(values)


def test_component_meet_never_discloses_more_than_either_input() -> None:
    policies = [
        CostDisclosurePolicy(
            granularity=granularity,
            identity_visibility=identity,
            amount_precision=amount,
            small_cell_minimum=minimum,
            rounding_increment=increment,
        )
        for granularity, identity, amount, minimum, increment in product(
            CostGranularity,
            CostIdentityVisibility,
            CostAmountPrecision,
            (1, 3),
            (Decimal("1"), Decimal("100")),
        )
    ]
    granularity_order = list(CostGranularity)
    identity_order = list(CostIdentityVisibility)
    amount_order = list(CostAmountPrecision)

    for left, right in product(policies, repeat=2):
        effective = left.meet(right)
        assert granularity_order.index(effective.granularity) <= min(
            granularity_order.index(left.granularity),
            granularity_order.index(right.granularity),
        )
        assert identity_order.index(effective.identity_visibility) <= min(
            identity_order.index(left.identity_visibility),
            identity_order.index(right.identity_visibility),
        )
        assert amount_order.index(effective.amount_precision) <= min(
            amount_order.index(left.amount_precision),
            amount_order.index(right.amount_precision),
        )
        assert effective.small_cell_minimum >= max(
            left.small_cell_minimum,
            right.small_cell_minimum,
        )
        assert effective.rounding_increment >= max(
            left.rounding_increment,
            right.rounding_increment,
        )


def test_disclosure_machine_values_match_the_frozen_w0_contract() -> None:
    assert tuple(CostGranularity) == ("none", "summary", "group", "resource")
    assert tuple(CostIdentityVisibility) == ("none", "pseudonymous", "exact")
    assert tuple(CostAmountPrecision) == ("none", "band", "rounded", "exact")


def test_disclosure_presets_enforce_server_side_shapes() -> None:
    records = (_record(), _record(record_id="costobs:2"), _record(record_id="costobs:3"))

    assert disclose_cost_records(records, DISCLOSURE_PRESETS["hidden"]) == ()
    aggregate = disclose_cost_records(records, DISCLOSURE_PRESETS["aggregate"])
    assert aggregate == (
        {
            "group_id": "production",
            "currency": "USD",
            "record_count": 3,
            "amount_rounded": "3700",
        },
    )
    masked = disclose_cost_records(
        records[:1],
        DISCLOSURE_PRESETS["masked"],
        pseudonym_key=bytes(range(32)),
    )
    assert masked[0]["resource"] != "resource/private"
    assert "amount_exact" not in masked[0]
    assert "amount_band" in masked[0]
    detailed = disclose_cost_records(records[:1], DISCLOSURE_PRESETS["detailed"])
    assert detailed[0]["resource"] == "resource/private"
    assert detailed[0]["amount_exact"] == "1234.56"

    summary = disclose_cost_records(
        records,
        CostDisclosurePolicy(
            granularity=CostGranularity.SUMMARY,
            identity_visibility=CostIdentityVisibility.NONE,
            amount_precision=CostAmountPrecision.ROUNDED,
        ),
    )
    assert summary[0]["record_count"] == 3
    assert "group_id" not in summary[0]


def test_small_aggregate_cells_are_suppressed() -> None:
    payload = disclose_cost_records((_record(),), DISCLOSURE_PRESETS["aggregate"])
    assert payload[0]["suppressed"] is True
    assert all("amount" not in key for key in payload[0])


def test_masked_disclosure_fails_closed_without_server_key() -> None:
    with pytest.raises(ValueError, match="server-held"):
        disclose_cost_records((_record(),), DISCLOSURE_PRESETS["masked"])


def test_projection_schema_is_versioned_and_authority_free() -> None:
    projection = CostGovernanceProjection(
        surface="overview",
        disclosure=DISCLOSURE_PRESETS["hidden"],
        generated_at=datetime(2026, 8, 28, tzinfo=UTC),
        source_authority="cost-observation",
        complete=True,
        analytics=CostAnalyticsProjection(
            source_authority="azure-cost-analytics",
            observed_at=datetime(2026, 8, 28, tzinfo=UTC),
            complete=True,
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
                    amount=Decimal("1000"),
                    current_spend=Decimal("120"),
                    forecast_spend=Decimal("480"),
                    currency="USD",
                    time_grain="Monthly",
                ),
            ),
            recommendations=(
                CostAnalyticsRecommendation(
                    recommendation_ref="recommendation:0123456789abcdef",
                    resource_ref="resource:0123456789abcdef",
                    resource_type="microsoft.compute/disks",
                    problem="Unattached disk",
                    solution="Review whether the disk is still required",
                    impact="Medium",
                    monthly_savings=Decimal("12"),
                    currency="USD",
                    observed_at=datetime(2026, 8, 28, tzinfo=UTC),
                    source_authority="azure-advisor",
                ),
            ),
        ),
    )
    payload = projection.model_dump(mode="json")
    assert not {"approval", "execution", "promotion", "authority"} & set(payload)
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "cost-governance-projection",
        payload,
        version="1.0.0",
    )


def test_all_cost_governance_boundaries_have_versioned_schemas() -> None:
    registry = PackageResourceSchemaRegistry()
    validator = JsonSchemaContractValidator(registry)
    grant = CostAccessGrant(
        grant_id="grant-1",
        principal_id="reader-1",
        revision=1,
        purpose="cost-governance-review",
        scopes=("*",),
        disclosure=DISCLOSURE_PRESETS["masked"],
        effective_at=datetime(2026, 8, 27, tzinfo=UTC),
        expires_at=datetime(2026, 8, 29, tzinfo=UTC),
        source_authority="operator-access-store",
    )
    availability = CostGovernanceAvailability(
        available=True,
        enabled=False,
        access_allowed=True,
        activation_revision=1,
        package_version="0.1.0",
        image_digest=f"sha256:{'b' * 64}",
        asset_manifest_digest=f"sha256:{'c' * 64}",
        semantic_profile_digest=f"sha256:{'d' * 64}",
        ontology_release_digest=f"sha256:{'e' * 64}",
        disclosure=DISCLOSURE_PRESETS["masked"],
    )

    validator.validate(
        "cost-governance-access-grant",
        grant.model_dump(mode="json"),
        version="1.0.0",
    )
    validator.validate(
        "cost-governance-availability",
        availability.model_dump(mode="json"),
        version="1.0.0",
    )
    validator.validate(
        "cost-governance-disclosure-policy",
        DISCLOSURE_PRESETS["masked"].model_dump(mode="json"),
        version="1.0.0",
    )
    ceiling = CostDisclosureCeiling(
        revision=1,
        disclosure=DISCLOSURE_PRESETS["masked"],
        effective_at=datetime(2026, 8, 27, tzinfo=UTC),
        source_authority="deployment-policy",
    )
    validator.validate(
        "cost-governance-disclosure-ceiling",
        ceiling.model_dump(mode="json"),
        version="1.0.0",
    )
    projection_schema = registry.get("cost-governance-projection", "1.0.0")
    definitions = projection_schema["$defs"]
    assert isinstance(definitions, dict)
    assert {
        "CostSummaryProjection",
        "CostTrendProjection",
        "CostResourceEfficiencyProjection",
        "CostOptimizationCaseProjection",
        "CostOutcomeProjection",
    } <= definitions.keys()


def test_availability_does_not_imply_enablement_or_other_authority() -> None:
    availability = CostGovernanceAvailability(
        available=True,
        enabled=False,
        access_allowed=True,
        activation_revision=1,
        package_version="0.1.0",
        image_digest=f"sha256:{'b' * 64}",
        asset_manifest_digest=f"sha256:{'c' * 64}",
        semantic_profile_digest=f"sha256:{'d' * 64}",
        ontology_release_digest=f"sha256:{'e' * 64}",
        disclosure=DISCLOSURE_PRESETS["hidden"],
    )
    payload = availability.model_dump(mode="json")

    assert payload["available"] is True
    assert payload["enabled"] is False
    assert not {"mode", "approval", "execution", "promotion"} & payload.keys()
    denied = availability.model_copy(update={"access_allowed": False, "disclosure": None})
    CostGovernanceAvailability.model_validate(denied.model_dump())
    assert denied.available is True
    assert denied.access_allowed is False
    with pytest.raises(ValueError, match="cannot be enabled"):
        availability.model_copy(
            update={
                "available": False,
                "enabled": True,
                "availability_reasons": ("host_incompatible",),
                "reason": "host_incompatible",
            }
        ).validate_state()
