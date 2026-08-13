"""Azure discovery coverage receipt and reconciliation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.discovery.router import BackendEligibility, compile_discovery_routes
from fdai.delivery.azure.discovery_coverage import (
    build_discovery_coverage_receipt,
    discovery_coverage_claims,
    reconcile_discovery_coverage,
)
from fdai.delivery.azure.discovery_profiles import default_azure_discovery_profiles
from fdai.delivery.azure.discovery_receipts import build_provider_execution_receipt
from fdai_service_contracts.discovery import (
    DiscoveryIntent,
    DiscoveryLimits,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    discovery_intent_digest,
)
from fdai_service_contracts.ontology_query import content_digest

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _coverage_receipt(profile_index: int, *, source: str = "live_canary"):
    profile = default_azure_discovery_profiles()[profile_index]
    operation = next(item for item in profile.operations if item.backend.value == "resource_graph")
    values: dict[str, object] = {
        "result_kind": DiscoveryResultKind.TYPES,
        "universes": operation.universes,
        "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
        "scope_digest": DIGEST,
        "predicates": (),
        "limits": DiscoveryLimits(max_results=100),
        "include_command_explanation": True,
        "unresolved_modifiers": (),
        "execution_authority": False,
    }
    intent = DiscoveryIntent(intent_digest=discovery_intent_digest(**values), **values)
    eligibility = BackendEligibility(
        operation_id=operation.operation_id,
        available=True,
        complete=True,
        scope_digest=DIGEST,
        predicate_digest=content_digest([]),
        output_schema_id=operation.output_schema_id,
        freshness_seconds=0,
    )
    plan = compile_discovery_routes(
        intent=intent,
        profile=profile,
        authorization_ceiling_digest=DIGEST,
        eligibility=(eligibility,),
    )[0].plan
    assert plan is not None
    execution = build_provider_execution_receipt(
        plan=plan,
        operation=operation,
        page_count=1,
        count=1,
        preview_rows=({"name": "resource-example", "type": "Example.Provider/widgets"},),
    )
    return build_discovery_coverage_receipt(
        profile=profile,
        plan=plan,
        execution_receipt=execution,
        observed_provider_types=("Example.Provider/widgets",),
        discovered_count=1,
        platform_version="resource-graph-2022-10-01",
        source=source,
        observed_at=NOW,
    )


def test_claims_cover_each_registered_arg_universe() -> None:
    claims = discovery_coverage_claims(default_azure_discovery_profiles())

    assert tuple(claim.universe.value for claim in claims) == (
        "arm_resources",
        "resource_containers",
    )


def test_reconciliation_requires_fresh_live_receipt_for_every_claim() -> None:
    claims = discovery_coverage_claims(default_azure_discovery_profiles())
    receipts = (_coverage_receipt(0), _coverage_receipt(1))

    result = reconcile_discovery_coverage(
        claims=claims,
        receipts=receipts,
        evaluated_at=NOW,
        max_age_seconds=3600,
    )

    assert result.complete is True
    assert result.gaps == ()
    assert result.execution_authority is False


def test_fixture_or_stale_receipt_cannot_validate_live_coverage() -> None:
    claims = discovery_coverage_claims(default_azure_discovery_profiles())
    fixture = _coverage_receipt(0, source="deterministic_fixture")
    stale = _coverage_receipt(1).model_copy(update={"observed_at": NOW - timedelta(days=2)})

    result = reconcile_discovery_coverage(
        claims=claims,
        receipts=(fixture, stale),
        evaluated_at=NOW,
        max_age_seconds=3600,
    )

    assert result.complete is False
    assert {gap.reason_code for gap in result.gaps} == {
        "live_receipt_missing",
        "receipt_stale",
    }


def test_wrong_profile_revision_remains_an_explicit_gap() -> None:
    claims = discovery_coverage_claims(default_azure_discovery_profiles())
    wrong_revision = replace(claims[0], profile_revision="2.0.0")

    result = reconcile_discovery_coverage(
        claims=(wrong_revision,),
        receipts=(_coverage_receipt(1),),
        evaluated_at=NOW,
        max_age_seconds=3600,
    )

    assert result.complete is False
    assert result.gaps[0].reason_code == "receipt_missing"
