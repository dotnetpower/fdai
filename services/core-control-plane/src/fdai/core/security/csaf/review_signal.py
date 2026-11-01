"""MSRC CSAF review signals for Heimdall's Drift ownership and Norns' RuleCandidate intake."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from fdai.rule_catalog.schema.msrc_csaf import (
    CsafDisposition,
    CsafThreatExploitStatus,
    MsrcCsafCrosswalkCatalog,
)
from fdai.shared.contracts.models import Severity

from .models import CsafAssessmentResult, CsafExposureStatus

CSAF_PACKAGE_KIND = "msrc-csaf-review"
CSAF_EVENT_TYPE = "msrc_csaf.vulnerability_drift"
CSAF_SCHEMA_VERSION = "1.0.0"

_WORKLOAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_CVE_RE = re.compile(r"^(?:CVE-[0-9]{4}-[0-9]{4,7}|ADV[0-9]{6})$")
_ACTION_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,255}$")

_SEVERITIES: tuple[str, ...] = tuple(item.value for item in Severity)
_EXPOSURES: tuple[str, ...] = tuple(item.value for item in CsafExposureStatus)
_PACKAGE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "workload_id",
        "source_revision",
        "inventory_generation",
        "scope_digest",
        "review_digest",
        "cve_count",
        "by_exposure",
        "by_severity",
        "critical_affected_count",
        "exploited_affected_count",
        "coverage_complete",
        "top_cve_ids",
        "recommended_action_types",
        "review_required",
        "grants_authority",
    }
)


class MsrcCsafReviewError(ValueError):
    """Raised when an MSRC CSAF review package is malformed or claims authority."""


def _count_map(raw: object, keys: Sequence[str], name: str) -> dict[str, int]:
    if not isinstance(raw, Mapping) or set(raw) != set(keys):
        raise MsrcCsafReviewError(f"{name} must count exactly {', '.join(keys)}")
    result: dict[str, int] = {}
    for key in keys:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MsrcCsafReviewError(f"{name}.{key} must be a non-negative integer")
        result[key] = value
    return result


def build_csaf_review_package(result: CsafAssessmentResult) -> dict[str, object]:
    """Build a strict, no-authority review package from a CsafAssessmentResult."""

    exposures = [item.exposure.value for item in result.findings]
    affected_or_mitigated = [
        item
        for item in result.findings
        if item.exposure in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
    ]
    severities = [item.severity.value for item in result.findings]
    by_exposure = {key: sum(1 for v in exposures if v == key) for key in _EXPOSURES}
    by_severity = {key: sum(1 for v in severities if v == key) for key in _SEVERITIES}
    critical_affected = sum(
        1
        for item in result.findings
        if item.exposure is CsafExposureStatus.AFFECTED and item.severity is Severity.CRITICAL
    )
    exploited_affected = sum(
        1
        for item in result.findings
        if item.exposure is CsafExposureStatus.AFFECTED
        and item.exploit_status is CsafThreatExploitStatus.EXPLOITED
    )
    coverage_complete = all(item.evidence_complete for item in result.findings) and (
        by_exposure[CsafExposureStatus.UNKNOWN.value] == 0
    )
    ranked_cves = sorted(
        item.cve_id
        for item in result.findings
        if item.exposure
        in {
            CsafExposureStatus.AFFECTED,
            CsafExposureStatus.UNKNOWN,
            CsafExposureStatus.MITIGATED,
        }
    )[:20]
    action_types = sorted(
        {
            item.recommended_action_type
            for item in affected_or_mitigated
            if item.recommended_action_type is not None
        }
    )[:16]
    digest_material = [
        result.workload_id,
        result.source_revision,
        result.inventory_generation,
        result.scope_digest,
        result.result_digest,
        ranked_cves,
    ]
    review_digest = hashlib.sha256(
        json.dumps(digest_material, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    package: dict[str, object] = {
        "schema_version": CSAF_SCHEMA_VERSION,
        "kind": CSAF_PACKAGE_KIND,
        "workload_id": result.workload_id,
        "source_revision": result.source_revision,
        "inventory_generation": result.inventory_generation,
        "scope_digest": result.scope_digest,
        "review_digest": review_digest,
        "cve_count": len(result.findings),
        "by_exposure": by_exposure,
        "by_severity": by_severity,
        "critical_affected_count": critical_affected,
        "exploited_affected_count": exploited_affected,
        "coverage_complete": coverage_complete,
        "top_cve_ids": ranked_cves,
        "recommended_action_types": action_types,
        "review_required": True,
        "grants_authority": False,
    }
    return validate_csaf_review_package(package)


def validate_csaf_review_package(raw: Mapping[str, object]) -> dict[str, object]:
    """Validate and return a defensive copy of an untrusted MSRC CSAF review package."""

    if not isinstance(raw, Mapping) or set(raw) != _PACKAGE_KEYS:
        raise MsrcCsafReviewError("MSRC CSAF review package fields are invalid")
    if raw["schema_version"] != CSAF_SCHEMA_VERSION or raw["kind"] != CSAF_PACKAGE_KIND:
        raise MsrcCsafReviewError("MSRC CSAF review package identity is invalid")
    if raw["review_required"] is not True or raw["grants_authority"] is not False:
        raise MsrcCsafReviewError("MSRC CSAF review package authority boundary is invalid")
    workload_id = raw["workload_id"]
    source_rev = raw["source_revision"]
    inv_gen = raw["inventory_generation"]
    scope_digest = raw["scope_digest"]
    review_digest = raw["review_digest"]
    if not isinstance(workload_id, str) or _WORKLOAD_ID_RE.fullmatch(workload_id) is None:
        raise MsrcCsafReviewError("workload_id is invalid")
    if not isinstance(source_rev, str) or _REVISION_RE.fullmatch(source_rev) is None:
        raise MsrcCsafReviewError("source_revision is invalid")
    if not isinstance(inv_gen, str) or _REVISION_RE.fullmatch(inv_gen) is None:
        raise MsrcCsafReviewError("inventory_generation is invalid")
    if not isinstance(scope_digest, str) or _SHA256_RE.fullmatch(scope_digest) is None:
        raise MsrcCsafReviewError("scope_digest is invalid")
    if not isinstance(review_digest, str) or _HEX64_RE.fullmatch(review_digest) is None:
        raise MsrcCsafReviewError("review_digest is invalid")
    cve_count = raw["cve_count"]
    if not isinstance(cve_count, int) or isinstance(cve_count, bool) or cve_count < 0:
        raise MsrcCsafReviewError("cve_count must be a non-negative integer")
    by_exposure = _count_map(raw["by_exposure"], _EXPOSURES, "by_exposure")
    by_severity = _count_map(raw["by_severity"], _SEVERITIES, "by_severity")
    if sum(by_exposure.values()) != cve_count:
        raise MsrcCsafReviewError("by_exposure does not add up to cve_count")
    if sum(by_severity.values()) != cve_count:
        raise MsrcCsafReviewError("by_severity does not add up to cve_count")
    critical_affected = raw["critical_affected_count"]
    exploited = raw["exploited_affected_count"]
    affected_count = by_exposure[CsafExposureStatus.AFFECTED.value]
    if (
        not isinstance(critical_affected, int)
        or isinstance(critical_affected, bool)
        or not 0 <= critical_affected <= min(affected_count, by_severity[Severity.CRITICAL.value])
    ):
        raise MsrcCsafReviewError("critical_affected_count is invalid")
    if (
        not isinstance(exploited, int)
        or isinstance(exploited, bool)
        or not 0 <= exploited <= affected_count
    ):
        raise MsrcCsafReviewError("exploited_affected_count is invalid")
    coverage_complete = raw["coverage_complete"]
    if not isinstance(coverage_complete, bool):
        raise MsrcCsafReviewError("coverage_complete must be a boolean")
    if coverage_complete and by_exposure[CsafExposureStatus.UNKNOWN.value] > 0:
        raise MsrcCsafReviewError("coverage_complete cannot be True when unknown CVEs exist")
    top_cves = raw["top_cve_ids"]
    actionable_total = (
        affected_count
        + by_exposure[CsafExposureStatus.UNKNOWN.value]
        + by_exposure[CsafExposureStatus.MITIGATED.value]
    )
    max_cves = min(20, actionable_total)
    if (
        not isinstance(top_cves, list)
        or len(top_cves) != max_cves
        or not all(isinstance(item, str) and _CVE_RE.fullmatch(item) for item in top_cves)
        or top_cves != sorted(set(top_cves))
    ):
        raise MsrcCsafReviewError("top_cve_ids must match the sorted actionable CVE count (<= 20)")
    actions = raw["recommended_action_types"]
    if (
        not isinstance(actions, list)
        or len(actions) > 16
        or not all(isinstance(item, str) and _ACTION_TYPE_RE.fullmatch(item) for item in actions)
        or actions != sorted(set(actions))
    ):
        raise MsrcCsafReviewError(
            "recommended_action_types must be a unique sorted list of canonical ActionTypes"
        )
    return {
        "schema_version": CSAF_SCHEMA_VERSION,
        "kind": CSAF_PACKAGE_KIND,
        "workload_id": workload_id,
        "source_revision": source_rev,
        "inventory_generation": inv_gen,
        "scope_digest": scope_digest,
        "review_digest": review_digest,
        "cve_count": cve_count,
        "by_exposure": by_exposure,
        "by_severity": by_severity,
        "critical_affected_count": critical_affected,
        "exploited_affected_count": exploited,
        "coverage_complete": coverage_complete,
        "top_cve_ids": list(top_cves),
        "recommended_action_types": list(actions),
        "review_required": True,
        "grants_authority": False,
    }


def csaf_review_decision(package: Mapping[str, object]) -> str:
    """Return ``coverage_incomplete``, ``urgent``, ``open``, or ``clear`` deterministically."""

    by_exposure = package["by_exposure"]
    if package["coverage_complete"] is not True or (
        isinstance(by_exposure, Mapping)
        and by_exposure.get(CsafExposureStatus.UNKNOWN.value, 0) > 0
    ):
        return "coverage_incomplete"
    exploited = package["exploited_affected_count"]
    critical_affected = package.get("critical_affected_count", 0)
    affected = (
        by_exposure.get(CsafExposureStatus.AFFECTED.value, 0)
        if isinstance(by_exposure, Mapping)
        else 0
    )
    mitigated = (
        by_exposure.get(CsafExposureStatus.MITIGATED.value, 0)
        if isinstance(by_exposure, Mapping)
        else 0
    )
    if (isinstance(exploited, int) and exploited > 0) or (
        isinstance(critical_affected, int) and critical_affected > 0
    ):
        return "urgent"
    if affected > 0 or mitigated > 0:
        return "open"
    return "clear"


def msrc_csaf_drift_payload(raw: Mapping[str, object]) -> dict[str, object]:
    """Project one validated MSRC CSAF review package into Heimdall's Drift ownership."""

    package = validate_csaf_review_package(raw)
    workload_id = str(package["workload_id"])
    digest = str(package["review_digest"])
    return {
        "producer_principal": "Heimdall",
        "kind": "msrc_csaf",
        "event_type": CSAF_EVENT_TYPE,
        "correlation_id": f"msrc-csaf:{workload_id}:{digest}",
        "idempotency_key": f"msrc-csaf-drift:{digest}",
        "resource_id": f"workload://{workload_id}",
        "target_type": "workload",
        "decision": csaf_review_decision(package),
        "authority_ceiling": "shadow",
        "human_approval_required": True,
        **{key: package[key] for key in sorted(package) if key not in ("schema_version", "kind")},
    }


def extract_csaf_rule_candidates(
    catalog: MsrcCsafCrosswalkCatalog,
    result: CsafAssessmentResult,
) -> tuple[dict[str, object], ...]:
    """Extract inert RuleCandidate payloads for Norns from CSAF findings and crosswalks."""

    if (
        result.source_revision != catalog.source_revision
        or result.crosswalk_digest != catalog.crosswalk_digest
        or result.advisories_digest != catalog.advisories_digest
    ):
        raise MsrcCsafReviewError(
            "extract_csaf_rule_candidates requires matching catalog and assessment pins"
        )
    advisory_urls = {advisory.tracking_id: advisory.source_url for advisory in catalog.advisories}
    product_map = {item.product_id: item for item in catalog.product_mappings}
    crosswalk_map = {item.cve_id: item for item in catalog.vulnerability_mappings}
    candidates: list[dict[str, object]] = []
    for finding in result.findings:
        if finding.exposure not in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}:
            continue
        mapping = crosswalk_map.get(finding.cve_id)
        if mapping is None or mapping.disposition not in {
            CsafDisposition.NEW_RULE_CANDIDATE,
            CsafDisposition.VERSION_OBSERVATION,
        }:
            continue
        products = [product_map[pid] for pid in mapping.product_ids if pid in product_map]
        canonical_types = sorted(
            {ctype for prod in products for ctype in prod.canonical_resource_types}
        )
        if not canonical_types:
            continue
        version_checks = [
            {
                "product_id": prod.product_id,
                "version_property": prod.version_property,
                "minimum_affected_version_inclusive": prod.minimum_affected_version_inclusive,
                "vulnerable_version_ceiling_exclusive": prod.vulnerable_version_ceiling_exclusive,
            }
            for prod in products
            if prod.version_property is not None
        ]
        if not version_checks and mapping.workaround_property is None:
            continue
        candidate_id = f"msrc-csaf.{finding.cve_id.lower()}"
        body: dict[str, object] = {
            "candidate_id": candidate_id,
            "cve_id": finding.cve_id,
            "advisory_tracking_id": finding.advisory_tracking_id,
            "source": "msrc_csaf",
            "source_revision": result.source_revision,
            "provenance_url": advisory_urls.get(
                finding.advisory_tracking_id,
                f"https://msrc.microsoft.com/update-guide/vulnerability/{finding.cve_id}",
            ),
            "severity": finding.severity.value,
            "exploit_status": finding.exploit_status.value,
            "resource_types": canonical_types,
            "version_checks": version_checks,
            "workaround_property": mapping.workaround_property,
            "workaround_expected_value": mapping.workaround_expected_value,
            "recommended_action_type": mapping.candidate_action_type,
            "state": "candidate",
            "mode": "shadow",
            "grants_authority": False,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        ).hexdigest()
        body["candidate_digest"] = f"sha256:{digest}"
        body["idempotency_key"] = f"norns-csaf-candidate:{digest}"
        candidates.append(body)
    return tuple(candidates)


__all__ = [
    "CSAF_EVENT_TYPE",
    "CSAF_PACKAGE_KIND",
    "CSAF_SCHEMA_VERSION",
    "MsrcCsafReviewError",
    "build_csaf_review_package",
    "csaf_review_decision",
    "extract_csaf_rule_candidates",
    "msrc_csaf_drift_payload",
    "validate_csaf_review_package",
]
