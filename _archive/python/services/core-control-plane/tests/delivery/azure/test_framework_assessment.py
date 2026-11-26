"""Azure adapter tests for exact framework scope and supporting evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.framework_assessment import (
    FrameworkApplicabilityDecision,
    FrameworkApplicabilityStatus,
    FrameworkAssessmentProfile,
    FrameworkAssessmentRequest,
    FrameworkAssessmentRuntime,
    FrameworkOwnerBinding,
    FrameworkSatisfactionStatus,
)
from fdai.delivery.azure.framework_assessment import (
    AzureAdvisorImpact,
    AzureAdvisorPillar,
    AzureFrameworkEvidenceAdapter,
    AzureWafSupportingEvidenceAdapter,
    WafExternalAssessmentArtifact,
    WafExternalSource,
    build_azure_advisor_supporting_artifact,
    normalize_azure_advisor_recommendation,
)
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkScopeKind,
    canonical_digest,
    load_framework_assessment_catalog,
)
from fdai.shared.providers.framework_assessment import (
    FrameworkObservationOutcome,
    FrameworkObservationRequest,
    FrameworkProviderObservation,
)

ROOT = Path(__file__).resolve().parents[5]
GENERATED = ROOT / "rule-catalog/framework-assessments/generated"
NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
SCOPE = canonical_digest({"scope": "example"})


def _catalog(name: str):
    return load_framework_assessment_catalog(GENERATED / f"{name}.json")


def test_estate_observation_resolves_exact_reviewed_requirement() -> None:
    catalog = _catalog("azure-caf")
    control = next(item for item in catalog.controls if item.control_id == "ready")
    requirement = next(item for item in control.evidence if item.kind.value == "observation")
    request = FrameworkObservationRequest(
        framework_id="azure-caf",
        catalog_digest=catalog.catalog_digest,
        scope_digest=SCOPE,
        control_ids=("ready",),
        inventory_generation=None,
        hierarchy_generation="hierarchy-1",
        evaluated_at=NOW,
    )
    observation = FrameworkProviderObservation(
        control_id="ready",
        requirement_ref=requirement.source_ref,
        evidence_ref="evidence://estate/hierarchy",
        evidence_kind="observation",
        producer=requirement.authoritative_producer or "",
        source_identity="azure-management",
        observed_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
        evidence_digest=canonical_digest({"hierarchy": "current"}),
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=FrameworkObservationOutcome.SATISFIED,
    )

    (receipt,) = AzureFrameworkEvidenceAdapter(catalog).to_receipts(
        request,
        (observation,),
    )

    assert receipt.requirement_id == requirement.requirement_id
    assert receipt.hierarchy_generation == "hierarchy-1"
    assert receipt.outcome is FrameworkSatisfactionStatus.SATISFIED


def test_estate_observation_rejects_unreviewed_producer() -> None:
    catalog = _catalog("azure-caf")
    request = FrameworkObservationRequest(
        framework_id="azure-caf",
        catalog_digest=catalog.catalog_digest,
        scope_digest=SCOPE,
        control_ids=("ready",),
        inventory_generation=None,
        hierarchy_generation="hierarchy-1",
        evaluated_at=NOW,
    )
    observation = FrameworkProviderObservation(
        control_id="ready",
        requirement_ref="estate-hierarchy-observation",
        evidence_ref="evidence://estate/hierarchy",
        evidence_kind="observation",
        producer="unreviewed-source",
        source_identity="azure-management",
        observed_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
        evidence_digest=canonical_digest({"hierarchy": "current"}),
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=FrameworkObservationOutcome.SATISFIED,
    )

    with pytest.raises(ValueError, match="not authoritative"):
        AzureFrameworkEvidenceAdapter(catalog).to_receipts(request, (observation,))


def test_external_scores_remain_supporting_only_in_runtime() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    artifact = WafExternalAssessmentArtifact(
        source=WafExternalSource.DEFENDER_SECURE_SCORE,
        source_identity="defender-for-cloud",
        scope_digest=SCOPE,
        control_ids=(control_id,),
        observed_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
        evidence_digest=canonical_digest({"score": "supporting"}),
        inventory_generation="inventory-1",
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
    )
    evidence = AzureWafSupportingEvidenceAdapter(catalog).to_receipts(artifact)
    decisions = tuple(
        FrameworkApplicabilityDecision(
            control_id=item.control_id,
            status=FrameworkApplicabilityStatus.APPLICABLE,
            requested_by="requester@example.com",
            owner_slot=item.owner_slot,
            cadence_days=item.cadence_days,
        )
        for item in catalog.controls
    )
    owners = tuple(
        FrameworkOwnerBinding(
            control_id=item.control_id,
            owner_slot=item.owner_slot,
            owner_identity=f"{item.owner_slot}@example.com",
        )
        for item in catalog.controls
    )
    profile = FrameworkAssessmentProfile.create(
        profile_id="waf-profile",
        framework_id="azure-waf",
        framework_version=catalog.framework_version,
        catalog_digest=catalog.catalog_digest,
        scope_kind=FrameworkScopeKind.WORKLOAD,
        scope_digest=SCOPE,
        ontology_release="2026.09",
        applicability=decisions,
        owners=owners,
        reviewed_by="reviewer@example.com",
        reviewed_at=NOW - timedelta(days=1),
        inventory_generation="inventory-1",
        hierarchy_generation=None,
        operating_model=None,
        environment_classes=(),
        regulatory_context=(),
    )

    result = FrameworkAssessmentRuntime(catalog).assess(
        FrameworkAssessmentRequest(
            assessment_id="waf-external",
            profile=profile,
            evaluated_at=NOW,
            recorded_at=NOW,
            evidence=evidence,
        )
    )
    control = next(item for item in result.controls if item.control_id == control_id)

    assert control.satisfaction is FrameworkSatisfactionStatus.UNKNOWN
    assert control.evidence_refs
    assert "supporting_evidence_only" in control.limitations


def test_normalize_azure_advisor_recommendation_and_build_waf_artifact() -> None:
    catalog = _catalog("azure-waf")
    arg_row = {
        "id": (
            "/subscriptions/00000000-0000-0000-0000-000000000001/providers/"
            "Microsoft.Advisor/recommendations/rec-1"
        ),
        "type": "microsoft.advisor/recommendations",
        "properties": {
            "recommendationTypeId": "00000000-0000-0000-0000-000000000000",
            "category": "HighAvailability",
            "impact": "High",
            "impactedField": "Microsoft.Compute/virtualMachines",
            "impactedValue": "vm-prod-01",
            "shortDescription": {
                "problem": "Single instance virtual machine has no availability SLA",
                "solution": "Add virtual machine to an availability set or zone",
            },
            "lastUpdated": "2026-09-10T00:45:00Z",
            "extendedProperties": {"assessmentKey": "val-1"},
        },
    }
    rec = normalize_azure_advisor_recommendation(arg_row)
    assert rec.waf_pillar is AzureAdvisorPillar.RELIABILITY
    assert rec.impact is AzureAdvisorImpact.HIGH
    assert rec.impacted_value == "vm-prod-01"
    assert rec.extended_properties == {"assessmentKey": "val-1"}

    artifact = build_azure_advisor_supporting_artifact(
        catalog,
        (arg_row,),
        scope_digest=SCOPE,
        inventory_generation="inventory-1",
        observed_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
        truncated=True,
    )
    assert artifact.source is WafExternalSource.AZURE_ADVISOR
    assert all(cid.startswith("RE:") for cid in artifact.control_ids)
    receipts = AzureWafSupportingEvidenceAdapter(catalog).to_receipts(artifact)
    assert receipts
    assert "evidence_truncated" in receipts[0].limitations
    assert "supporting_evidence_only" in receipts[0].limitations
