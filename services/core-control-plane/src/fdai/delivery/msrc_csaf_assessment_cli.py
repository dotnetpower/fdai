"""One-shot MSRC CSAF 2.0 shadow assessment runner and Operator projection builder."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.csaf import (
    CsafAssessmentRequest,
    CsafAssessmentResult,
    CsafExposureStatus,
    CsafVexJustification,
    CsafVulnerabilityFinding,
    MsrcCsafAssessmentRuntime,
    build_csaf_review_package,
    compute_csaf_risk_score,
    extract_csaf_rule_candidates,
    msrc_csaf_drift_payload,
    to_security_control_observations,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.msrc_csaf import (
    CsafDisposition,
    CsafThreatExploitStatus,
    CsafVulnerabilityRecord,
    MsrcCsafCrosswalkCatalog,
    classify_kev_sla_tier,
    load_msrc_csaf_crosswalk_catalog,
)

MSRC_CSAF_PROJECTION_KEY = "operator-projection:workflow:msrc-csaf.list"
MSRC_CSAF_REVIEW_STATE_PREFIX = "runtime:msrc-csaf-review:"
_REPO_ROOT = repo_asset_root()
_DEFAULT_CROSSWALK_PATH = _REPO_ROOT / "rule-catalog/collected/msrc-csaf/crosswalk.json"
_CVE_YEAR_RE = re.compile(r"^CVE-(\d{4})-")


@dataclass(frozen=True, slots=True)
class MsrcCsafAssessmentRunReceipt:
    """Deterministic receipt from one shadow MSRC CSAF assessment run."""

    assessment: CsafAssessmentResult
    review_package: dict[str, object]
    drift_payload: dict[str, object]
    operator_projection: dict[str, object]
    # C21: Include extracted Norns rule candidates and SecurityControlObservation count
    rule_candidates: tuple[dict[str, object], ...] = ()
    security_observations_count: int = 0
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("MsrcCsafAssessmentRunReceipt MUST NOT grant execution_authority")
        if self.security_observations_count < 0:
            raise ValueError("security_observations_count MUST be non-negative")


def build_msrc_csaf_state_store_record(
    receipt: MsrcCsafAssessmentRunReceipt,
) -> tuple[str, dict[str, object]]:
    """Build the state-store key and record consumed by Heimdall.msrc_csaf_facts() (C23)."""

    if receipt.execution_authority is not False:
        raise ValueError("state-store record requires a shadow no-authority receipt")
    key = f"{MSRC_CSAF_REVIEW_STATE_PREFIX}{receipt.assessment.workload_id}"
    record: dict[str, object] = {
        "package": receipt.review_package,
        "recorded_at": receipt.assessment.recorded_at.isoformat(),
    }
    return key, record


def build_msrc_csaf_operator_projection(
    catalog: MsrcCsafCrosswalkCatalog,
    result: CsafAssessmentResult | None = None,
) -> dict[str, object]:
    """Build the no-authority Operator workflow projection for `/msrc-csaf-controls`."""

    if result is not None:
        if result.execution_authority is not False or result.mode != "shadow":
            raise ValueError("MSRC CSAF Operator projection requires a shadow no-authority result")
        if (
            result.source_revision != catalog.source_revision
            or result.advisories_digest != catalog.advisories_digest
            or result.crosswalk_digest != catalog.crosswalk_digest
        ):
            raise ValueError("MSRC CSAF assessment result pins do not match catalog")

    findings_by_cve = (
        {finding.cve_id: finding for finding in result.findings} if result is not None else {}
    )
    products_by_id = {prod.product_id: prod for prod in catalog.product_mappings}
    vuln_meta: dict[str, tuple[str, str, str, str, str, str, bool, CsafVulnerabilityRecord]] = {}
    for adv in catalog.advisories:
        for vuln in adv.vulnerabilities:
            vuln_meta[vuln.cve_id] = (
                adv.tracking_id,
                adv.title,
                adv.source_url,
                adv.document_digest,
                adv.initial_release_date.isoformat().replace("+00:00", "Z"),
                adv.current_release_date.isoformat().replace("+00:00", "Z"),
                adv.signature_verified,
                vuln,
            )

    controls: list[dict[str, object]] = []
    for mapping in catalog.vulnerability_mappings:
        meta = vuln_meta.get(mapping.cve_id)
        if meta is None:
            raise ValueError(f"missing advisory vulnerability metadata for {mapping.cve_id}")
        (
            tracking_id,
            adv_title,
            source_url,
            doc_digest,
            init_date,
            cur_date,
            sig_verified,
            vuln,
        ) = meta
        prods = [products_by_id[pid] for pid in mapping.product_ids]
        primary_rtype = next(
            (p.canonical_resource_type for p in prods if p.canonical_resource_type is not None),
            "unmapped",
        )
        year_match = _CVE_YEAR_RE.match(mapping.cve_id)
        year = year_match.group(1) if year_match is not None else init_date[:4]
        finding = findings_by_cve.get(mapping.cve_id)
        sla_tier, _due_days = classify_kev_sla_tier(
            vuln.severity,
            vuln.exploit_status,
            vuln.cvss_vector,
        )
        profile = vuln.attack_profile
        if finding is not None:
            eval_status = finding.evaluation.value
            exposure = finding.exposure.value
            vex_just = finding.vex_justification.value
            risk_score = finding.risk_score
        elif mapping.disposition is CsafDisposition.AMBIGUOUS_OR_BLOCKED or mapping.blocked_reasons:
            eval_status = "blocked"
            exposure = "unknown"
            vex_just = CsafVexJustification.UNDETERMINED_EVIDENCE_GAP.value
            risk_score = compute_csaf_risk_score(
                cvss_base_score=vuln.cvss_base_score,
                exploit_status=vuln.exploit_status,
                cvss_vector=vuln.cvss_vector,
                exposure=CsafExposureStatus.UNKNOWN,
            )
        else:
            eval_status = "not_evaluated"
            exposure = "unknown"
            vex_just = CsafVexJustification.UNDETERMINED_EVIDENCE_GAP.value
            risk_score = compute_csaf_risk_score(
                cvss_base_score=vuln.cvss_base_score,
                exploit_status=vuln.exploit_status,
                cvss_vector=vuln.cvss_vector,
                exposure=CsafExposureStatus.UNKNOWN,
            )

        # V19: Include KEV SLA tier, VEX justification, risk score, and attack-surface flags
        controls.append(
            {
                "cve_id": mapping.cve_id,
                "year": year,
                "title": vuln.title,
                "advisory_tracking_id": tracking_id,
                "advisory_title": adv_title,
                "source_url": source_url,
                "document_digest": doc_digest,
                "initial_release_date": init_date,
                "current_release_date": cur_date,
                "signature_verified": sig_verified,
                "severity": vuln.severity.value,
                "cvss_base_score": vuln.cvss_base_score,
                "exploit_status": vuln.exploit_status.value,
                "publicly_disclosed": vuln.publicly_disclosed,
                "disposition": mapping.disposition.value,
                "mapping_state": mapping.mapping_state.value,
                "primary_resource_type": primary_rtype,
                "evaluation_status": eval_status,
                "exposure": exposure,
                "kev_sla_tier": sla_tier.value,
                "vex_justification": vex_just,
                "risk_score": risk_score,
                "is_zero_click": profile.is_zero_click,
                "is_pre_auth_network": profile.is_network_reachable and profile.is_unauthenticated,
                "is_wormable_candidate": profile.is_wormable_candidate,
                # C22: Include per-CVE resource counts and limitations in Operator projection
                "affected_resource_count": (
                    len(finding.affected_resource_ids) if finding is not None else 0
                ),
                "mitigated_resource_count": (
                    len(finding.mitigated_resource_ids) if finding is not None else 0
                ),
                "fixed_resource_count": (
                    len(finding.fixed_resource_ids) if finding is not None else 0
                ),
                "limitations": list(finding.limitations) if finding is not None else [],
                "execution_authority": False,
            }
        )

    # V20: Expand summary with critical, zero-click, wormable, and KEV SLA tier counts
    by_sla: dict[str, int] = {}
    for item in controls:
        tier_key = str(item["kev_sla_tier"])
        by_sla[tier_key] = by_sla.get(tier_key, 0) + 1
    summary = {
        "total": len(controls),
        "affected": sum(1 for item in controls if item["exposure"] == "affected"),
        "mitigated": sum(1 for item in controls if item["exposure"] == "mitigated"),
        "fixed": sum(1 for item in controls if item["exposure"] == "fixed"),
        "not_applicable": sum(1 for item in controls if item["exposure"] == "not_applicable"),
        "unknown": sum(1 for item in controls if item["exposure"] == "unknown"),
        "exploited_affected": sum(
            1
            for item in controls
            if item["exposure"] == "affected"
            and item["exploit_status"] == CsafThreatExploitStatus.EXPLOITED.value
        ),
        "critical_affected": sum(
            1
            for item in controls
            if item["exposure"] == "affected" and item["severity"] == "critical"
        ),
        "zero_click_affected": sum(
            1
            for item in controls
            if item["exposure"] == "affected" and item["is_zero_click"] is True
        ),
        "wormable_affected": sum(
            1
            for item in controls
            if item["exposure"] == "affected" and item["is_wormable_candidate"] is True
        ),
        "by_kev_sla_tier": dict(sorted(by_sla.items())),
    }

    payload: dict[str, object] = {
        "schema_version": catalog.schema_version,
        "source_id": "msrc_csaf",
        "source_revision": catalog.source_revision,
        "advisories_digest": catalog.advisories_digest,
        "crosswalk_digest": catalog.crosswalk_digest,
        "evaluation_source": (
            "msrc-csaf-shadow-assessment" if result is not None else "repository-catalog"
        ),
        "last_workload_id": result.workload_id if result is not None else None,
        "last_evaluated_at": result.evaluated_at.isoformat() if result is not None else None,
        "summary": summary,
        "controls": controls,
    }
    revision = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {
        "_revision": revision,
        **payload,
    }


class MsrcCsafAssessmentRunner:
    """Evaluate one scoped request against the pinned MSRC CSAF catalog in shadow mode."""

    def __init__(self, crosswalk_path: Path = _DEFAULT_CROSSWALK_PATH) -> None:
        self._catalog = load_msrc_csaf_crosswalk_catalog(crosswalk_path)
        self._runtime = MsrcCsafAssessmentRuntime(self._catalog)

    @property
    def catalog(self) -> MsrcCsafCrosswalkCatalog:
        return self._catalog

    def run(self, request: CsafAssessmentRequest) -> MsrcCsafAssessmentRunReceipt:
        assessment = self._runtime.assess(request)
        review_package = build_csaf_review_package(assessment)
        drift_payload = msrc_csaf_drift_payload(review_package)
        projection = build_msrc_csaf_operator_projection(self._catalog, assessment)
        candidates = extract_csaf_rule_candidates(self._catalog, assessment)
        observations = to_security_control_observations(assessment)
        return MsrcCsafAssessmentRunReceipt(
            assessment=assessment,
            review_package=review_package,
            drift_payload=drift_payload,
            operator_projection=projection,
            rule_candidates=candidates,
            security_observations_count=len(observations),
            execution_authority=False,
        )


def filter_actionable_findings(
    result: CsafAssessmentResult,
    *,
    min_risk_score: float = 0.0,
    exploited_only: bool = False,
) -> tuple[CsafVulnerabilityFinding, ...]:
    """Filter and prioritize actionable CSAF findings by risk score and exploit status (V21)."""

    selected = [
        finding
        for finding in result.findings
        if finding.exposure in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
        and finding.risk_score >= min_risk_score
        and (not exploited_only or finding.exploit_status is CsafThreatExploitStatus.EXPLOITED)
    ]
    selected.sort(key=lambda item: (-item.risk_score, -item.cvss_base_score, item.cve_id))
    return tuple(selected)
