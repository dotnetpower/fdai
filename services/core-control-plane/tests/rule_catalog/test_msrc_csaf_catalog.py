"""Contract and security-hardening tests for MSRC CSAF 2.0 schema and OASIS parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.msrc_csaf import (
    CsafRemediationCategory,
    CsafRemediationRecord,
    CsafSchemaError,
    CsafThreatExploitStatus,
    MsrcCsafCrosswalkCatalog,
    compare_dotted_versions,
    is_version_in_affected_window,
    load_msrc_csaf_crosswalk_catalog,
    parse_dotted_version,
    severity_for_cvss_score,
    version_train_prefix,
)
from fdai.rule_catalog.schema.msrc_csaf_oasis_parser import parse_oasis_csaf_bytes
from fdai.rule_catalog.schema.wara_assessment import canonical_digest
from fdai.shared.contracts.models import Severity

REPO_ROOT = Path(__file__).resolve().parents[4]
CROSSWALK_PATH = REPO_ROOT / "rule-catalog" / "collected" / "msrc-csaf" / "crosswalk.json"


def _sample_oasis_payload(
    *, threat_details: str = "Publicly Disclosed:Yes;Exploited:Yes"
) -> dict[str, object]:
    return {
        "document": {
            "category": "csaf_security_advisory",
            "csaf_version": "2.0",
            "title": "Azure Kubernetes Service Elevation of Privilege",
            "publisher": {
                "category": "vendor",
                "name": "Microsoft Security Response Center",
                "namespace": "https://msrc.microsoft.com",
            },
            "tracking": {
                "id": "MSRC-2026-AKS-001",
                "initial_release_date": "2026-10-13T00:00:00Z",
                "current_release_date": "2026-10-14T00:00:00Z",
                "revision_history": [
                    {"number": "1.0", "date": "2026-10-13T00:00:00Z", "summary": "Initial"},
                    {"number": "2.0", "date": "2026-10-14T00:00:00Z", "summary": "Updated"},
                ],
            },
        },
        "product_tree": {
            "branches": [
                {
                    "category": "vendor",
                    "name": "Microsoft",
                    "branches": [
                        {
                            "category": "product_name",
                            "name": "Azure Kubernetes Service 1.28",
                            "product": {
                                "product_id": "AZURE-AKS-1.28",
                                "name": "Azure Kubernetes Service 1.28 Node Image",
                                "product_identification_helper": {
                                    "cpe": "cpe:/a:microsoft:azure_kubernetes_service:1.28"
                                },
                            },
                        }
                    ],
                }
            ]
        },
        "vulnerabilities": [
            {
                "cve": "CVE-2026-20001",
                "title": "AKS Node Image Elevation of Privilege",
                "product_status": {
                    "known_affected": ["AZURE-AKS-1.28"],
                    "fixed": [],
                    "known_not_affected": [],
                },
                "scores": [
                    {
                        "products": ["AZURE-AKS-1.28"],
                        "cvss_v3": {
                            "version": "3.1",
                            "baseScore": 8.8,
                            "temporalScore": 8.2,
                            "vectorString": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
                        },
                    }
                ],
                "threats": [
                    {
                        "category": "exploit_status",
                        "details": threat_details,
                    }
                ],
                "remediations": [
                    {
                        "category": "vendor_fix",
                        "product_ids": ["AZURE-AKS-1.28"],
                        "details": "Upgrade AKS Kubernetes version to 1.28.9 or later.",
                        "fixed_version": "1.28.9",
                        "url": "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-20001",
                    }
                ],
            }
        ],
    }


def test_shipped_msrc_csaf_crosswalk_loads_and_verifies_digests() -> None:
    catalog = load_msrc_csaf_crosswalk_catalog(CROSSWALK_PATH)
    assert catalog.source_id == "msrc_csaf"
    assert len(catalog.advisories) == 267
    assert len(catalog.product_mappings) == 268
    assert len(catalog.vulnerability_mappings) == 268


def test_dotted_version_comparison_and_train_prefix_are_numeric() -> None:
    assert parse_dotted_version("1.28.9") == (1, 28, 9)
    assert compare_dotted_versions("1.28.9", "1.28.10") == -1
    assert compare_dotted_versions("1.28.0", "1.28") == 0
    assert version_train_prefix("1.28.0", "1.28.9") == (1, 28)
    assert is_version_in_affected_window(
        "1.28.5",
        minimum_inclusive="1.28.0",
        ceiling_exclusive="1.28.9",
    )
    assert not is_version_in_affected_window(
        "1.28.9",
        minimum_inclusive="1.28.0",
        ceiling_exclusive="1.28.9",
    )
    with pytest.raises(CsafSchemaError, match="canonical numeric dotted version"):
        parse_dotted_version("01.28.9")
    with pytest.raises(CsafSchemaError, match="minimum_inclusive < ceiling_exclusive"):
        is_version_in_affected_window(
            "1.28.5",
            minimum_inclusive="1.28.9",
            ceiling_exclusive="1.28.9",
        )


def test_oasis_parser_distinguishes_exploited_no_from_exploited_yes() -> None:
    """Regression for C-05: 'Exploited:No' must never match substring 'exploited'."""
    payload = _sample_oasis_payload(
        threat_details=(
            "Publicly Disclosed:No;Exploited:No;Latest Software Release:Exploitation Less Likely"
        )
    )
    raw = json.dumps(payload).encode("utf-8")
    import hashlib

    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    doc = parse_oasis_csaf_bytes(
        raw,
        expected_sha256=digest,
        signature_verified=True,
        source_url="https://msrc.microsoft.com/csaf/advisories/2026/msrc-2026-aks-001.json",
    )
    vuln = doc.vulnerabilities[0]
    assert vuln.exploit_status is CsafThreatExploitStatus.EXPLOITATION_LESS_LIKELY
    assert vuln.publicly_disclosed is False


def test_oasis_parser_rejects_unverified_signature_and_digest_mismatch() -> None:
    payload = _sample_oasis_payload()
    raw = json.dumps(payload).encode("utf-8")
    import hashlib

    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    with pytest.raises(CsafSchemaError, match="signature"):
        parse_oasis_csaf_bytes(
            raw,
            expected_sha256=digest,
            signature_verified=False,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/msrc-2026-aks-001.json",
        )
    with pytest.raises(CsafSchemaError, match="byte digest"):
        parse_oasis_csaf_bytes(
            raw,
            expected_sha256="sha256:" + "0" * 64,
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/msrc-2026-aks-001.json",
        )


def test_oasis_parser_rejects_duplicate_keys_nonfinite_scores_and_foreign_publisher() -> None:
    """Regression for C-06, C-11, and C-15."""
    import hashlib

    dup_raw = b'{"document":{},"document":{},"product_tree":{},"vulnerabilities":[]}'
    dup_digest = f"sha256:{hashlib.sha256(dup_raw).hexdigest()}"
    with pytest.raises(CsafSchemaError, match="duplicate JSON key"):
        parse_oasis_csaf_bytes(
            dup_raw,
            expected_sha256=dup_digest,
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/dup.json",
        )

    nan_raw = b'{"document":{"score":NaN},"product_tree":{},"vulnerabilities":[]}'
    nan_digest = f"sha256:{hashlib.sha256(nan_raw).hexdigest()}"
    with pytest.raises(CsafSchemaError, match="non-finite JSON constant"):
        parse_oasis_csaf_bytes(
            nan_raw,
            expected_sha256=nan_digest,
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/nan.json",
        )

    foreign = _sample_oasis_payload()
    assert isinstance(foreign["document"], dict)
    foreign["document"]["publisher"] = {"namespace": "https://evil.example.com"}
    foreign_raw = json.dumps(foreign).encode("utf-8")
    foreign_digest = f"sha256:{hashlib.sha256(foreign_raw).hexdigest()}"
    with pytest.raises(CsafSchemaError, match="publisher.namespace"):
        parse_oasis_csaf_bytes(
            foreign_raw,
            expected_sha256=foreign_digest,
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/foreign.json",
        )


def test_url_and_strict_scalar_guards_reject_path_traversal_and_type_coercion() -> None:
    """Regression for C-03 and C-05."""
    with pytest.raises(ValueError, match="clean HTTPS URL"):
        CsafRemediationRecord(
            category=CsafRemediationCategory.WORKAROUND,
            product_ids=("AZURE-AKS-1.28",),
            details="Disable public access",
            workaround_property="public_network_access_enabled",
            workaround_expected_value=False,
            url="https://msrc.microsoft.com/csaf/../../evil",
        )

    raw_catalog = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))
    raw_catalog["product_mappings"][0]["vulnerable_version_ceiling_exclusive"] = "1.28.99"
    temp = dict(raw_catalog)
    temp.pop("crosswalk_digest")
    raw_catalog["crosswalk_digest"] = canonical_digest(temp)
    with pytest.raises(ValueError, match="does not match advisory vendor_fix"):
        MsrcCsafCrosswalkCatalog.model_validate(raw_catalog)

    for cat_mutate, cat_match in (
        (lambda c: c.__setitem__("advisories_digest", "sha256:" + "9" * 64), "advisories_digest"),
        (lambda c: c.__setitem__("crosswalk_digest", "sha256:" + "9" * 64), "crosswalk_digest"),
        (
            lambda c: next(
                m for m in c["vulnerability_mappings"] if m["cve_id"] == "CVE-2026-20001"
            ).__setitem__("workaround_expected_value", True),
            "crosswalk workaround",
        ),
        (
            lambda c: next(
                m for m in c["vulnerability_mappings"] if m["cve_id"] == "CVE-2026-20001"
            ).__setitem__("advisory_tracking_id", "MSRC-OTHER"),
            "advisory_tracking_id mismatch",
        ),
        (
            lambda c: next(
                m for m in c["vulnerability_mappings"] if m["cve_id"] == "CVE-2026-20001"
            ).__setitem__("product_ids", ["AZURE-STORAGE-TLS"]),
            "product_ids mismatch",
        ),
    ):
        cand_cat = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))
        cat_mutate(cand_cat)  # type: ignore[no-untyped-call]
        if cat_match != "crosswalk_digest":
            t = dict(cand_cat)
            t.pop("crosswalk_digest")
            cand_cat["crosswalk_digest"] = canonical_digest(t)
        with pytest.raises(ValueError, match=cat_match):
            MsrcCsafCrosswalkCatalog.model_validate(cand_cat)


def test_cvss_score_band_mapping() -> None:
    assert severity_for_cvss_score(9.0) is Severity.CRITICAL
    assert severity_for_cvss_score(7.5) is Severity.HIGH
    assert severity_for_cvss_score(5.0) is Severity.MEDIUM
    assert severity_for_cvss_score(2.1) is Severity.LOW
    assert compare_dotted_versions("1.29.0", "1.28.9") == 1
    with pytest.raises(CsafSchemaError, match="finite number"):
        severity_for_cvss_score(-0.1)


def test_msrc_csaf_schema_boundary_validations(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from fdai.rule_catalog.schema.msrc_csaf import (
        CsafAdvisoryDocument,
        CsafDisposition,
        CsafProductBranch,
        CsafProductCrosswalk,
        CsafVulnerabilityCrosswalk,
        CsafVulnerabilityRecord,
    )
    from fdai.rule_catalog.schema.wara_assessment import (
        ResourceTypeDisposition,
        WaraMappingState,
    )

    with pytest.raises(ValueError, match="whitespace or control"):
        CsafRemediationRecord(
            category=CsafRemediationCategory.WORKAROUND,
            product_ids=("AZURE-AKS-1.28",),
            details="Disable public access",
            workaround_property="public_network_access_enabled",
            workaround_expected_value=False,
            url="https://msrc.microsoft.com/csaf /bad",
        )
    with pytest.raises(ValueError, match="non-empty, unique, and ordered"):
        CsafRemediationRecord(
            category=CsafRemediationCategory.WORKAROUND,
            product_ids=("B", "A"),
            details="Disable",
            workaround_property="prop",
            workaround_expected_value=True,
        )
    with pytest.raises(ValueError, match="fixed_version or kb_article"):
        CsafRemediationRecord(
            category=CsafRemediationCategory.VENDOR_FIX,
            product_ids=("AZURE-AKS-1.28",),
            details="Upgrade",
        )
    with pytest.raises(ValueError, match="supplied together"):
        CsafRemediationRecord(
            category=CsafRemediationCategory.WORKAROUND,
            product_ids=("AZURE-AKS-1.28",),
            details="Disable",
            workaround_property="prop",
        )

    # Vulnerability validation branches
    with pytest.raises(ValueError, match="known_affected"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=8.0,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.HIGH,
            exploit_status=CsafThreatExploitStatus.UNPROVEN,
            publicly_disclosed=False,
            known_affected_product_ids=(),
        )
    with pytest.raises(ValueError, match="unique and ordered"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=8.0,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.HIGH,
            exploit_status=CsafThreatExploitStatus.UNPROVEN,
            publicly_disclosed=False,
            known_affected_product_ids=("B", "A"),
        )
    with pytest.raises(ValueError, match="mutually disjoint"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=8.0,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.HIGH,
            exploit_status=CsafThreatExploitStatus.UNPROVEN,
            publicly_disclosed=False,
            known_affected_product_ids=("A",),
            fixed_product_ids=("A",),
        )
    with pytest.raises(ValueError, match="cannot be lower than CVSS band"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=9.5,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.MEDIUM,
            exploit_status=CsafThreatExploitStatus.UNPROVEN,
            publicly_disclosed=False,
            known_affected_product_ids=("A",),
        )
    with pytest.raises(ValueError, match="publicly_disclosed=True"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=8.0,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.HIGH,
            exploit_status=CsafThreatExploitStatus.EXPLOITED,
            publicly_disclosed=False,
            known_affected_product_ids=("A",),
        )
    with pytest.raises(ValueError, match="reference known_affected or fixed"):
        CsafVulnerabilityRecord(
            cve_id="CVE-2026-20001",
            title="Test",
            cvss_base_score=8.0,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            severity=Severity.HIGH,
            exploit_status=CsafThreatExploitStatus.UNPROVEN,
            publicly_disclosed=False,
            known_affected_product_ids=("A",),
            remediations=(
                CsafRemediationRecord(
                    category=CsafRemediationCategory.VENDOR_FIX,
                    product_ids=("OTHER",),
                    details="Fix",
                    kb_article="KB5000001",
                ),
            ),
        )

    # Advisory validation branches
    valid_vuln = CsafVulnerabilityRecord(
        cve_id="CVE-2026-20001",
        title="Test",
        cvss_base_score=8.0,
        cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
        severity=Severity.HIGH,
        exploit_status=CsafThreatExploitStatus.UNPROVEN,
        publicly_disclosed=False,
        known_affected_product_ids=("A",),
    )
    t0 = datetime(2026, 10, 13, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        CsafAdvisoryDocument(
            tracking_id="MSRC-1",
            title="Title",
            initial_release_date=datetime(2026, 10, 13),
            current_release_date=t0,
            revision_count=1,
            source_url="https://msrc.microsoft.com/csaf/advisories/1.json",
            document_digest="sha256:" + "1" * 64,
            signature_verified=True,
            products=(CsafProductBranch(product_id="A", name="Prod A"),),
            vulnerabilities=(valid_vuln,),
        )
    with pytest.raises(ValueError, match="precede initial_release_date"):
        CsafAdvisoryDocument(
            tracking_id="MSRC-1",
            title="Title",
            initial_release_date=t0,
            current_release_date=datetime(2026, 10, 12, tzinfo=UTC),
            revision_count=1,
            source_url="https://msrc.microsoft.com/csaf/advisories/1.json",
            document_digest="sha256:" + "1" * 64,
            signature_verified=True,
            products=(CsafProductBranch(product_id="A", name="Prod A"),),
            vulnerabilities=(valid_vuln,),
        )
    with pytest.raises(ValueError, match="undeclared product_tree"):
        CsafAdvisoryDocument(
            tracking_id="MSRC-1",
            title="Title",
            initial_release_date=t0,
            current_release_date=t0,
            revision_count=1,
            source_url="https://msrc.microsoft.com/csaf/advisories/1.json",
            document_digest="sha256:" + "1" * 64,
            signature_verified=True,
            products=(CsafProductBranch(product_id="B", name="Prod B"),),
            vulnerabilities=(valid_vuln,),
        )

    # Product & Vulnerability Crosswalk validation branches
    with pytest.raises(ValueError, match="canonical disposition"):
        CsafProductCrosswalk(
            product_id="A",
            product_name="Prod A",
            disposition=ResourceTypeDisposition.CANONICAL,
            canonical_resource_type=None,
            canonical_resource_types=(),
            provider_resource_types=("microsoft.compute/virtualmachines",),
            reviewer="fdai",
        )
    with pytest.raises(ValueError, match="version_property and version window"):
        CsafProductCrosswalk(
            product_id="A",
            product_name="Prod A",
            disposition=ResourceTypeDisposition.CANONICAL,
            canonical_resource_type="vm",
            canonical_resource_types=("vm",),
            provider_resource_types=("microsoft.compute/virtualmachines",),
            reviewer="fdai",
        )
    with pytest.raises(ValueError, match="minimum_affected_version_inclusive"):
        CsafProductCrosswalk(
            product_id="A",
            product_name="Prod A",
            disposition=ResourceTypeDisposition.CANONICAL,
            canonical_resource_type="vm",
            canonical_resource_types=("vm",),
            provider_resource_types=("microsoft.compute/virtualmachines",),
            version_property="os_version",
            minimum_affected_version_inclusive="2.0",
            vulnerable_version_ceiling_exclusive="1.0",
            reviewer="fdai",
        )
    with pytest.raises(ValueError, match="existing_rule_id"):
        CsafVulnerabilityCrosswalk(
            cve_id="CVE-2026-20001",
            advisory_tracking_id="MSRC-1",
            disposition=CsafDisposition.EXISTING_RULE,
            mapping_state=WaraMappingState.FULL,
            product_ids=("A",),
        )
    with pytest.raises(ValueError, match="blocked_reasons"):
        CsafVulnerabilityCrosswalk(
            cve_id="CVE-2026-20001",
            advisory_tracking_id="MSRC-1",
            disposition=CsafDisposition.AMBIGUOUS_OR_BLOCKED,
            mapping_state=WaraMappingState.UNMAPPED,
            product_ids=("A",),
        )

    # File loader checks
    missing = tmp_path / "missing.json"
    with pytest.raises(CsafSchemaError, match="regular non-symlink"):
        load_msrc_csaf_crosswalk_catalog(missing)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CsafSchemaError, match="not valid UTF-8 JSON"):
        load_msrc_csaf_crosswalk_catalog(bad_json)


def test_oasis_parser_additional_branches() -> None:
    import hashlib

    payload = _sample_oasis_payload(threat_details="Exploitation Unlikely")
    assert isinstance(payload["product_tree"], dict)
    payload["product_tree"]["full_product_names"] = [
        {"product_id": "AZURE-EXTRA", "name": "Azure Extra Product"}
    ]
    raw = json.dumps(payload).encode("utf-8")
    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    doc = parse_oasis_csaf_bytes(
        raw,
        expected_sha256=digest,
        signature_verified=True,
        source_url="https://msrc.microsoft.com/csaf/advisories/2026/extra.json",
    )
    assert len(doc.products) == 2
    assert doc.vulnerabilities[0].exploit_status is CsafThreatExploitStatus.EXPLOITATION_UNLIKELY

    with pytest.raises(CsafSchemaError, match="payload size"):
        parse_oasis_csaf_bytes(
            b"",
            expected_sha256=digest,
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/empty.json",
        )
    with pytest.raises(CsafSchemaError, match="expected_sha256"):
        parse_oasis_csaf_bytes(
            raw,
            expected_sha256="invalid-digest",
            signature_verified=True,
            source_url="https://msrc.microsoft.com/csaf/advisories/2026/bad-sha.json",
        )

    for mutate, match_str in (
        (
            lambda p: p["threats"].__setitem__(0, {"details": "Exploited:Maybe"}),
            "invalid MSRC CSAF Exploited",
        ),
        (
            lambda p: p["threats"].__setitem__(0, {"details": "Publicly Disclosed:Maybe"}),
            "invalid MSRC CSAF Publicly Disclosed",
        ),
        (
            lambda p: p["scores"][0].__setitem__("products", ["UNKNOWN-PROD"]),
            "score products",
        ),
        (
            lambda p: p["scores"][0]["cvss_v3"].__setitem__("baseScore", True),
            "baseScore MUST be a finite number",
        ),
        (
            lambda p: p["scores"][0]["cvss_v3"].__setitem__("temporalScore", True),
            "temporalScore MUST be a finite number",
        ),
        (
            lambda p: p.__setitem__("remediations", "not-a-list"),
            "remediations MUST be a list",
        ),
        (
            lambda p: p["remediations"].__setitem__(0, "not-an-obj"),
            "remediation entry MUST be an object",
        ),
        (
            lambda p: p["remediations"][0].__setitem__("product_ids", "not-a-list"),
            "remediation product_ids MUST be a list",
        ),
    ):
        cand = _sample_oasis_payload()
        assert isinstance(cand["vulnerabilities"], list)
        mutate(cand["vulnerabilities"][0])
        b = json.dumps(cand).encode("utf-8")
        d = f"sha256:{hashlib.sha256(b).hexdigest()}"
        with pytest.raises(CsafSchemaError, match=match_str):
            parse_oasis_csaf_bytes(
                b,
                expected_sha256=d,
                signature_verified=True,
                source_url="https://msrc.microsoft.com/csaf/advisories/2026/err.json",
            )

    for doc_mutate, doc_match in (
        (lambda root: root.__setitem__("document", "bad"), "requires document"),
        (
            lambda root: root["document"].__setitem__("publisher", "bad"),
            "publisher MUST be an object",
        ),
        (lambda root: root["document"].__setitem__("tracking", "bad"), "tracking is required"),
        (
            lambda root: root["document"]["tracking"].__setitem__("revision_history", []),
            "revision_history",
        ),
        (
            lambda root: root["product_tree"].__setitem__("branches", "bad"),
            "branches MUST be a list",
        ),
        (
            lambda root: root["product_tree"]["branches"].__setitem__(0, "bad"),
            "branch item MUST be an object",
        ),
        (
            lambda root: root["product_tree"].__setitem__("full_product_names", "bad"),
            "full_product_names MUST be a list",
        ),
        (
            lambda root: root["product_tree"].__setitem__("full_product_names", ["bad"]),
            "full_product_name item MUST be an object",
        ),
        (
            lambda root: root["vulnerabilities"].__setitem__(0, "bad"),
            "vulnerability item MUST be an object",
        ),
        (
            lambda root: root["vulnerabilities"][0].__setitem__("product_status", "bad"),
            "product_status is required",
        ),
    ):
        cand_root = _sample_oasis_payload()
        doc_mutate(cand_root)  # type: ignore[no-untyped-call]
        b = json.dumps(cand_root).encode("utf-8")
        d = f"sha256:{hashlib.sha256(b).hexdigest()}"
        with pytest.raises(CsafSchemaError, match=doc_match):
            parse_oasis_csaf_bytes(
                b,
                expected_sha256=d,
                signature_verified=True,
                source_url="https://msrc.microsoft.com/csaf/advisories/2026/doc-err.json",
            )
