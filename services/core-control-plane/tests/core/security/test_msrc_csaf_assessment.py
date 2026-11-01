"""Deterministic MSRC CSAF vulnerability assessment and hardening regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.security.assessment import SecurityVerdict, build_security_assessment
from fdai.core.security.csaf import (
    CsafAssessmentRequest,
    CsafEvaluationStatus,
    CsafEvidenceReceipt,
    CsafExposureStatus,
    CsafScopedResource,
    MsrcCsafAssessmentRuntime,
    MsrcCsafReviewError,
    build_csaf_review_package,
    csaf_review_decision,
    extract_csaf_rule_candidates,
    msrc_csaf_drift_payload,
    to_security_control_observations,
    validate_csaf_review_package,
)
from fdai.rule_catalog.schema.msrc_csaf import load_msrc_csaf_crosswalk_catalog

REPO_ROOT = Path(__file__).resolve().parents[5]
CROSSWALK_PATH = REPO_ROOT / "rule-catalog" / "collected" / "msrc-csaf" / "crosswalk.json"
_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _runtime() -> MsrcCsafAssessmentRuntime:
    return MsrcCsafAssessmentRuntime(load_msrc_csaf_crosswalk_catalog(CROSSWALK_PATH))


def _request(
    runtime: MsrcCsafAssessmentRuntime,
    resources: tuple[CsafScopedResource, ...],
    *,
    evidence: tuple[CsafEvidenceReceipt, ...] = (),
) -> CsafAssessmentRequest:
    cat = runtime.catalog
    return CsafAssessmentRequest(
        assessment_id="csaf-assessment-001",
        source_revision=cat.source_revision,
        crosswalk_digest=cat.crosswalk_digest,
        advisories_digest=cat.advisories_digest,
        ontology_release="ontology-v1",
        inventory_generation="inv-gen-001",
        workload_id="payments-prod",
        resources=resources,
        evaluated_at=_NOW,
        recorded_at=_NOW + timedelta(seconds=5),
        evidence=evidence,
    )


def test_vulnerable_aks_and_fixed_storage_produce_expected_shadow_outcomes() -> None:
    runtime = _runtime()
    resources = (
        CsafScopedResource(
            resource_id="aks-prod-01",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=15),
            properties={
                "kubernetes_version": "1.28.4",
                "public_network_access_enabled": True,
            },
        ),
        CsafScopedResource(
            resource_id="st-prod-01",
            provider_resource_type="Microsoft.Storage/storageAccounts",
            observed_at=_NOW - timedelta(minutes=10),
            properties={"minimum_tls_version": "1.2"},
        ),
    )
    result = runtime.assess(_request(runtime, resources))
    assert result.mode == "shadow"
    assert result.execution_authority is False
    by_cve = {item.cve_id: item for item in result.findings}

    aks_finding = by_cve["CVE-2026-20001"]
    assert aks_finding.exposure is CsafExposureStatus.AFFECTED
    assert aks_finding.affected_resource_ids == ("aks-prod-01",)
    assert aks_finding.recommended_action_type == "remediate.disable-public-access"
    assert aks_finding.evidence_complete is True

    storage_finding = by_cve["CVE-2026-20002"]
    assert storage_finding.exposure is CsafExposureStatus.FIXED
    assert storage_finding.fixed_resource_ids == ("st-prod-01",)
    assert storage_finding.recommended_action_type is None

    unmapped = by_cve["CVE-2026-20003"]
    assert unmapped.evaluation is CsafEvaluationStatus.BLOCKED
    assert unmapped.exposure is CsafExposureStatus.UNKNOWN


def test_workaround_property_mitigates_affected_version_but_strict_bool_blocks_int() -> None:
    """Regression for C-03: integer 0 must not satisfy boolean False workaround."""
    runtime = _runtime()
    mitigated_res = (
        CsafScopedResource(
            resource_id="aks-mitigated",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={
                "kubernetes_version": "1.28.4",
                "public_network_access_enabled": False,
            },
        ),
    )
    res1 = runtime.assess(_request(runtime, mitigated_res))
    by_cve1 = {item.cve_id: item for item in res1.findings}
    assert by_cve1["CVE-2026-20001"].exposure is CsafExposureStatus.MITIGATED

    int_res = (
        CsafScopedResource(
            resource_id="aks-int-zero",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={
                "kubernetes_version": "1.28.4",
                "public_network_access_enabled": 0,
            },
        ),
    )
    res2 = runtime.assess(_request(runtime, int_res))
    by_cve2 = {item.cve_id: item for item in res2.findings}
    assert by_cve2["CVE-2026-20001"].exposure is CsafExposureStatus.AFFECTED


def test_invalid_or_conflicting_evidence_receipt_fails_closed_to_unknown() -> None:
    """Regression for C-01 and C-14: invalid or conflicting receipts never fail open."""
    runtime = _runtime()
    resources = (
        CsafScopedResource(
            resource_id="aks-prod-01",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={
                "kubernetes_version": "1.28.4",
                "public_network_access_enabled": False,
            },
        ),
    )
    base_req = _request(runtime, resources)
    synthetic_receipt = CsafEvidenceReceipt(
        cve_id="CVE-2026-20001",
        evidence_ref="receipt:synthetic",
        evidence_kind="manual_attestation",
        producer="operator",
        scope_digest=base_req.scope_digest,
        source_revision=base_req.source_revision,
        inventory_generation=base_req.inventory_generation,
        observed_at=_NOW - timedelta(minutes=2),
        recorded_at=_NOW - timedelta(minutes=1),
        evidence_digest="sha256:" + "a" * 64,
        freshness_ceiling_seconds=3600,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=True,
        provider_error=None,
        outcome=CsafExposureStatus.MITIGATED,
    )
    res = runtime.assess(_request(runtime, resources, evidence=(synthetic_receipt,)))
    finding = {item.cve_id: item for item in res.findings}["CVE-2026-20001"]
    assert finding.exposure is CsafExposureStatus.UNKNOWN
    assert "synthetic_evidence_rejected" in finding.limitations

    conflicting_fixed_receipt = CsafEvidenceReceipt(
        cve_id="CVE-2026-20001",
        evidence_ref="receipt:fixed-claim",
        evidence_kind="manual_attestation",
        producer="operator",
        scope_digest=base_req.scope_digest,
        source_revision=base_req.source_revision,
        inventory_generation=base_req.inventory_generation,
        observed_at=_NOW - timedelta(minutes=2),
        recorded_at=_NOW - timedelta(minutes=1),
        evidence_digest="sha256:" + "b" * 64,
        freshness_ceiling_seconds=3600,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=CsafExposureStatus.FIXED,
    )
    res_conflict = runtime.assess(
        _request(runtime, resources, evidence=(conflicting_fixed_receipt,))
    )
    finding_conflict = {item.cve_id: item for item in res_conflict.findings}["CVE-2026-20001"]
    assert finding_conflict.exposure is CsafExposureStatus.UNKNOWN
    assert "conflicting_inventory_and_receipt_outcome" in finding_conflict.limitations


def test_different_version_train_is_not_misclassified_as_fixed_and_retains_evidence_ref() -> None:
    """Regression for C-02 and C-13: 1.29.1 against 1.28 train is NOT_APPLICABLE with ref."""
    runtime = _runtime()
    resources = (
        CsafScopedResource(
            resource_id="aks-129",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"kubernetes_version": "1.29.1"},
        ),
    )
    res = runtime.assess(_request(runtime, resources))
    finding = {item.cve_id: item for item in res.findings}["CVE-2026-20001"]
    assert finding.exposure is CsafExposureStatus.NOT_APPLICABLE
    assert finding.evidence_refs == ("inventory:aks-129:kubernetes_version=1.29.1",)


def test_review_package_and_security_assessment_integration_preserve_multi_resource_scope() -> None:
    """Regression for C-04, C-09, and C-12."""
    runtime = _runtime()
    resources = (
        CsafScopedResource(
            resource_id="aks-prod-01",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"kubernetes_version": "1.28.4"},
        ),
        CsafScopedResource(
            resource_id="aks-prod-02",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"kubernetes_version": "1.28.5"},
        ),
        CsafScopedResource(
            resource_id="st-prod-01",
            provider_resource_type="Microsoft.Storage/storageAccounts",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"minimum_tls_version": "1.2"},
        ),
    )
    result = runtime.assess(_request(runtime, resources))
    controls = to_security_control_observations(result)
    security_report = build_security_assessment(
        (),
        scope="payments-prod",
        assessed_at=_NOW,
        controls=controls,
    )
    assert security_report.verdict in {SecurityVerdict.ATTENTION, SecurityVerdict.CRITICAL}
    assert security_report.blocks_action is False
    assert security_report.cve_count == 268
    assert security_report.affected_resource_count >= 3

    package = build_csaf_review_package(result)
    assert csaf_review_decision(package) == "coverage_incomplete"
    drift = msrc_csaf_drift_payload(package)
    assert drift["authority_ceiling"] == "shadow"
    assert drift["grants_authority"] is False

    candidates = extract_csaf_rule_candidates(runtime.catalog, result)
    assert len(candidates) >= 1
    cve_20001_cand = next(item for item in candidates if item["cve_id"] == "CVE-2026-20001")
    assert cve_20001_cand["grants_authority"] is False
    assert str(cve_20001_cand["candidate_digest"]).startswith("sha256:")

    tampered = dict(package, grants_authority=True)
    with pytest.raises(MsrcCsafReviewError, match="authority"):
        validate_csaf_review_package(tampered)


def test_models_runtime_and_review_signal_boundary_validations() -> None:
    runtime = _runtime()
    valid_res = CsafScopedResource(
        resource_id="aks-prod-01",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW - timedelta(minutes=5),
        properties={"kubernetes_version": "1.28.4"},
    )
    req = _request(runtime, (valid_res,))
    result = runtime.assess(req)
    assert "result_digest" in result.to_dict(include_digest=True)
    assert "result_digest" not in result.to_dict(include_digest=False)

    # ScopedResource boundary checks
    with pytest.raises(ValueError, match="identity and provider type"):
        CsafScopedResource(
            resource_id="",
            provider_resource_type="Microsoft.Compute/virtualMachines",
            observed_at=_NOW,
            properties={},
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        CsafScopedResource(
            resource_id="vm-1",
            provider_resource_type="Microsoft.Compute/virtualMachines",
            observed_at=datetime(2026, 10, 15),
            properties={},
        )
    with pytest.raises(ValueError, match="unique and ordered"):
        CsafScopedResource(
            resource_id="vm-1",
            provider_resource_type="Microsoft.Compute/virtualMachines",
            observed_at=_NOW,
            properties={},
            workload_tags=("b", "a"),
        )
    with pytest.raises(ValueError, match="property key"):
        CsafScopedResource(
            resource_id="vm-1",
            provider_resource_type="Microsoft.Compute/virtualMachines",
            observed_at=_NOW,
            properties={"INVALID KEY": "1"},
        )
    with pytest.raises(ValueError, match="MUST be str, bool, or int"):
        CsafScopedResource(
            resource_id="vm-1",
            provider_resource_type="Microsoft.Compute/virtualMachines",
            observed_at=_NOW,
            properties={"key": 1.5},  # type: ignore[dict-item]
        )

    # Request and Result boundary checks
    with pytest.raises(ValueError, match="request pins MUST be non-empty"):
        CsafAssessmentRequest(
            assessment_id="",
            source_revision=req.source_revision,
            crosswalk_digest=req.crosswalk_digest,
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(valid_res,),
            evaluated_at=_NOW,
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="crosswalk digest MUST be lowercase SHA-256"):
        CsafAssessmentRequest(
            assessment_id="id",
            source_revision=req.source_revision,
            crosswalk_digest="bad",
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(valid_res,),
            evaluated_at=_NOW,
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="at least one scoped resource"):
        CsafAssessmentRequest(
            assessment_id="id",
            source_revision=req.source_revision,
            crosswalk_digest=req.crosswalk_digest,
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(),
            evaluated_at=_NOW,
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="unique and ordered"):
        CsafAssessmentRequest(
            assessment_id="id",
            source_revision=req.source_revision,
            crosswalk_digest=req.crosswalk_digest,
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(valid_res, valid_res),
            evaluated_at=_NOW,
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        CsafAssessmentRequest(
            assessment_id="id",
            source_revision=req.source_revision,
            crosswalk_digest=req.crosswalk_digest,
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(valid_res,),
            evaluated_at=datetime(2026, 10, 15),
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="recorded_at MUST follow evaluated_at"):
        CsafAssessmentRequest(
            assessment_id="id",
            source_revision=req.source_revision,
            crosswalk_digest=req.crosswalk_digest,
            advisories_digest=req.advisories_digest,
            ontology_release="v1",
            inventory_generation="g1",
            workload_id="w1",
            resources=(valid_res,),
            evaluated_at=_NOW,
            recorded_at=_NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="shadow-only"):
        result.__class__(
            **{
                **{k: getattr(result, k) for k in result.__dataclass_fields__},
                "mode": "enforce",
            }
        )
    with pytest.raises(ValueError, match="result_digest"):
        result.__class__(
            **{
                **{k: getattr(result, k) for k in result.__dataclass_fields__},
                "result_digest": "bad",
            }
        )

    # EvidenceReceipt boundary checks
    with pytest.raises(ValueError, match="canonical CVE"):
        CsafEvidenceReceipt(
            cve_id="NOT-A-CVE",
            evidence_ref="ref-1",
            evidence_kind="manual",
            producer="op",
            scope_digest=req.scope_digest,
            source_revision=req.source_revision,
            inventory_generation=req.inventory_generation,
            observed_at=_NOW,
            recorded_at=_NOW,
            evidence_digest="sha256:" + "a" * 64,
            freshness_ceiling_seconds=60,
            complete=True,
            truncated=False,
            conflicting=False,
            synthetic=False,
            provider_error=None,
            outcome=CsafExposureStatus.MITIGATED,
        )
    with pytest.raises(ValueError, match="recorded_at MUST follow observed_at"):
        CsafEvidenceReceipt(
            cve_id="CVE-2026-20001",
            evidence_ref="ref-1",
            evidence_kind="manual",
            producer="op",
            scope_digest=req.scope_digest,
            source_revision=req.source_revision,
            inventory_generation=req.inventory_generation,
            observed_at=_NOW,
            recorded_at=_NOW - timedelta(seconds=1),
            evidence_digest="sha256:" + "a" * 64,
            freshness_ceiling_seconds=60,
            complete=True,
            truncated=False,
            conflicting=False,
            synthetic=False,
            provider_error=None,
            outcome=CsafExposureStatus.MITIGATED,
        )

    # Runtime pin mismatch checks
    with pytest.raises(ValueError, match="source_revision mismatch"):
        runtime.assess(
            CsafAssessmentRequest(
                assessment_id="id",
                source_revision="wrong-rev",
                crosswalk_digest=req.crosswalk_digest,
                advisories_digest=req.advisories_digest,
                ontology_release="v1",
                inventory_generation="g1",
                workload_id="w1",
                resources=(valid_res,),
                evaluated_at=_NOW,
                recorded_at=_NOW,
            )
        )
    with pytest.raises(ValueError, match="matching catalog and assessment pins"):
        extract_csaf_rule_candidates(
            runtime.catalog,
            result.__class__(
                **{
                    **{k: getattr(result, k) for k in result.__dataclass_fields__},
                    "source_revision": "other",
                }
            ),
        )

    # Stale, future, missing, and malformed version property branches
    stale_res = CsafScopedResource(
        resource_id="aks-stale",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW - timedelta(days=30),
        properties={"kubernetes_version": "1.28.4"},
    )
    future_res = CsafScopedResource(
        resource_id="aks-future",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW + timedelta(minutes=10),
        properties={"kubernetes_version": "1.28.4"},
    )
    missing_ver = CsafScopedResource(
        resource_id="aks-missing",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW - timedelta(minutes=1),
        properties={},
    )
    bad_ver = CsafScopedResource(
        resource_id="aks-bad",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW - timedelta(minutes=1),
        properties={"kubernetes_version": "not-a-version"},
    )
    non_str_ver = CsafScopedResource(
        resource_id="aks-int",
        provider_resource_type="Microsoft.ContainerService/managedClusters",
        observed_at=_NOW - timedelta(minutes=1),
        properties={"kubernetes_version": 128},
    )
    for res_item, expected_limitation in (
        (stale_res, "stale_resource_observation"),
        (future_res, "future_resource_observation"),
        (missing_ver, "missing_version_property"),
        (bad_ver, "malformed_version_property"),
        (non_str_ver, "invalid_version_property_type"),
    ):
        r = runtime.assess(_request(runtime, (res_item,)))
        f = {item.cve_id: item for item in r.findings}["CVE-2026-20001"]
        assert f.exposure is CsafExposureStatus.UNKNOWN
        assert expected_limitation in f.limitations

    # Receipt rejection branches (scope, source_revision, inventory_generation, provider_error,
    # incomplete, truncated, conflicting, future, stale, duplicate, conflicting outcomes)
    for overrides, expected_reason in (
        ({"scope_digest": "sha256:" + "9" * 64}, "scope_mismatch"),
        ({"source_revision": "other-rev"}, "source_revision_mismatch"),
        ({"inventory_generation": "other-gen"}, "inventory_generation_mismatch"),
        ({"provider_error": "timeout"}, "provider_error"),
        ({"complete": False}, "incomplete_evidence"),
        ({"truncated": True}, "truncated_evidence"),
        ({"conflicting": True}, "conflicting_evidence"),
        (
            {
                "observed_at": _NOW + timedelta(minutes=2),
                "recorded_at": _NOW + timedelta(minutes=3),
            },
            "future_evidence_timestamp",
        ),
        (
            {"observed_at": _NOW - timedelta(days=5), "freshness_ceiling_seconds": 60},
            "stale_evidence",
        ),
    ):
        receipt_kwargs = {
            "cve_id": "CVE-2026-20001",
            "evidence_ref": "receipt:test",
            "evidence_kind": "manual",
            "producer": "op",
            "scope_digest": req.scope_digest,
            "source_revision": req.source_revision,
            "inventory_generation": req.inventory_generation,
            "observed_at": _NOW - timedelta(minutes=1),
            "recorded_at": _NOW,
            "evidence_digest": "sha256:" + "a" * 64,
            "freshness_ceiling_seconds": 3600,
            "complete": True,
            "truncated": False,
            "conflicting": False,
            "synthetic": False,
            "provider_error": None,
            "outcome": CsafExposureStatus.MITIGATED,
            **overrides,
        }
        rec = CsafEvidenceReceipt(**receipt_kwargs)  # type: ignore[arg-type]
        r_rec = runtime.assess(_request(runtime, (valid_res,), evidence=(rec,)))
        f_rec = {item.cve_id: item for item in r_rec.findings}["CVE-2026-20001"]
        assert expected_reason in f_rec.limitations

    # Review package validation error branches
    pkg = build_csaf_review_package(result)
    for bad_pkg, err_match in (
        ({"wrong": 1}, "fields are invalid"),
        ({**pkg, "kind": "wrong"}, "identity is invalid"),
        ({**pkg, "workload_id": "bad id!"}, "workload_id is invalid"),
        ({**pkg, "source_revision": "BAD REV"}, "source_revision is invalid"),
        ({**pkg, "inventory_generation": "BAD GEN"}, "inventory_generation is invalid"),
        ({**pkg, "scope_digest": "bad"}, "scope_digest is invalid"),
        ({**pkg, "review_digest": "bad"}, "review_digest is invalid"),
        ({**pkg, "cve_count": -1}, "cve_count must be"),
        ({**pkg, "by_exposure": {"affected": 1}}, "by_exposure must count"),
        ({**pkg, "by_exposure": {**pkg["by_exposure"], "affected": -1}}, "non-negative integer"),  # type: ignore[dict-item]
        ({**pkg, "by_exposure": {**pkg["by_exposure"], "affected": 99}}, "does not add up"),  # type: ignore[dict-item]
        ({**pkg, "critical_affected_count": 99}, "critical_affected_count is invalid"),
        ({**pkg, "exploited_affected_count": 99}, "exploited_affected_count is invalid"),
        ({**pkg, "coverage_complete": "yes"}, "coverage_complete must be a boolean"),
        ({**pkg, "coverage_complete": True}, "cannot be True when unknown CVEs exist"),
        ({**pkg, "top_cve_ids": ["NOT-CVE"]}, "top_cve_ids"),
        ({**pkg, "recommended_action_types": ["BAD ACTION"]}, "recommended_action_types"),
    ):
        with pytest.raises(MsrcCsafReviewError, match=err_match):
            validate_csaf_review_package(bad_pkg)
