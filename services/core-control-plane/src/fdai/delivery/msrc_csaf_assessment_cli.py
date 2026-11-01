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
    MsrcCsafAssessmentRuntime,
    build_csaf_review_package,
    msrc_csaf_drift_payload,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.msrc_csaf import (
    CsafDisposition,
    CsafVulnerabilityRecord,
    MsrcCsafCrosswalkCatalog,
    load_msrc_csaf_crosswalk_catalog,
)

MSRC_CSAF_PROJECTION_KEY = "operator-projection:workflow:msrc-csaf.list"
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
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("MsrcCsafAssessmentRunReceipt MUST NOT grant execution_authority")


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
        if finding is not None:
            eval_status = finding.evaluation.value
            exposure = finding.exposure.value
        elif mapping.disposition is CsafDisposition.AMBIGUOUS_OR_BLOCKED or mapping.blocked_reasons:
            eval_status = "blocked"
            exposure = "unknown"
        else:
            eval_status = "not_evaluated"
            exposure = "unknown"

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
                "execution_authority": False,
            }
        )

    payload: dict[str, object] = {
        "schema_version": catalog.schema_version,
        "source_id": "msrc_csaf",
        "source_revision": catalog.source_revision,
        "advisories_digest": catalog.advisories_digest,
        "crosswalk_digest": catalog.crosswalk_digest,
        "evaluation_source": (
            "msrc-csaf-shadow-assessment" if result is not None else "repository-catalog"
        ),
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
        return MsrcCsafAssessmentRunReceipt(
            assessment=assessment,
            review_package=review_package,
            drift_payload=drift_payload,
            operator_projection=projection,
            execution_authority=False,
        )
