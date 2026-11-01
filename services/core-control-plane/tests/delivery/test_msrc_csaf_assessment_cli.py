"""Focused tests for MsrcCsafAssessmentRunner and Operator projection builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.security.csaf import (
    CsafAssessmentRequest,
    CsafScopedResource,
)
from fdai.delivery.msrc_csaf_assessment_cli import (
    MSRC_CSAF_PROJECTION_KEY,
    MsrcCsafAssessmentRunner,
    build_msrc_csaf_operator_projection,
    build_msrc_csaf_state_store_record,
    filter_actionable_findings,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CROSSWALK_PATH = REPO_ROOT / "rule-catalog/collected/msrc-csaf/crosswalk.json"


def test_runner_evaluates_9058_cves_and_builds_shadow_operator_projection() -> None:
    runner = MsrcCsafAssessmentRunner(CROSSWALK_PATH)
    catalog = runner.catalog
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    request = CsafAssessmentRequest(
        assessment_id="csaf-cli-run-001",
        source_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        advisories_digest=catalog.advisories_digest,
        ontology_release="ontology-v1",
        inventory_generation="inv-gen-20261015-01",
        workload_id="payments-prod",
        resources=(
            CsafScopedResource(
                resource_id="aks-prod-01",
                provider_resource_type="Microsoft.ContainerService/managedClusters",
                observed_at=now - timedelta(minutes=15),
                properties={
                    "kubernetes_version": "1.28.4",
                    "public_network_access_enabled": True,
                },
            ),
        ),
        evaluated_at=now,
        recorded_at=now + timedelta(seconds=5),
    )

    receipt = runner.run(request)
    assert receipt.execution_authority is False
    assert MSRC_CSAF_PROJECTION_KEY == "operator-projection:workflow:msrc-csaf.list"

    proj = receipt.operator_projection
    assert str(proj["_revision"]).startswith("sha256:")
    assert proj["evaluation_source"] == "msrc-csaf-shadow-assessment"
    assert proj["crosswalk_digest"] == catalog.crosswalk_digest
    controls = proj["controls"]
    assert isinstance(controls, list)
    assert len(controls) == 9058
    aks_row = next(item for item in controls if item["cve_id"] == "CVE-2026-20001")
    assert aks_row["evaluation_status"] == "evaluated"
    assert aks_row["exposure"] == "affected"
    assert aks_row["affected_resource_count"] == 1
    assert aks_row["execution_authority"] is False
    assert isinstance(proj["summary"], dict)
    assert proj["summary"]["total"] == 9058
    assert receipt.rule_candidates
    assert receipt.security_observations_count >= 9058

    state_key, state_record = build_msrc_csaf_state_store_record(receipt)
    assert state_key == "runtime:msrc-csaf-review:payments-prod"
    assert state_record["package"] == receipt.review_package

    # V19-V21: Verify actionable finding filter and expanded summary
    exploited_findings = filter_actionable_findings(
        receipt.assessment,
        min_risk_score=70.0,
        exploited_only=True,
    )
    assert any(f.cve_id == "CVE-2026-20001" for f in exploited_findings)
    assert "by_kev_sla_tier" in proj["summary"]
    assert aks_row["kev_sla_tier"] == "immediate_24h"
    assert aks_row["vex_justification"] == "affected_requires_remediation"

    static_proj = build_msrc_csaf_operator_projection(catalog, None)
    assert static_proj["evaluation_source"] == "repository-catalog"
    static_controls = static_proj["controls"]
    assert isinstance(static_controls, list)
    assert len(static_controls) == 9058

    with pytest.raises(ValueError, match="MUST NOT grant execution_authority"):
        type(receipt)(
            assessment=receipt.assessment,
            review_package=receipt.review_package,
            drift_payload=receipt.drift_payload,
            operator_projection=proj,
            execution_authority=True,
        )
