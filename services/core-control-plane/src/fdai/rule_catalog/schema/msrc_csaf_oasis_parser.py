"""Deterministic OASIS CSAF 2.0 raw advisory parser for MSRC feeds."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.rule_catalog.schema.msrc_csaf import (
    CsafAdvisoryDocument,
    CsafProductBranch,
    CsafRemediationCategory,
    CsafRemediationRecord,
    CsafSchemaError,
    CsafThreatExploitStatus,
    CsafVulnerabilityRecord,
    severity_for_cvss_score,
)
from fdai.shared.contracts.models import Severity

_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_RAW_CSAF_BYTES = 1_048_576
_MAX_BRANCH_DEPTH = 8
_EXPLOIT_STATUS_MAP: dict[str, CsafThreatExploitStatus] = {
    "exploited": CsafThreatExploitStatus.EXPLOITED,
    "exploitation more likely": CsafThreatExploitStatus.EXPLOITATION_MORE_LIKELY,
    "exploitation_more_likely": CsafThreatExploitStatus.EXPLOITATION_MORE_LIKELY,
    "exploitation less likely": CsafThreatExploitStatus.EXPLOITATION_LESS_LIKELY,
    "exploitation_less_likely": CsafThreatExploitStatus.EXPLOITATION_LESS_LIKELY,
    "exploitation unlikely": CsafThreatExploitStatus.EXPLOITATION_UNLIKELY,
    "exploitation_unlikely": CsafThreatExploitStatus.EXPLOITATION_UNLIKELY,
    "publicly disclosed": CsafThreatExploitStatus.PUBLICLY_DISCLOSED,
    "publicly_disclosed": CsafThreatExploitStatus.PUBLICLY_DISCLOSED,
    "unproven": CsafThreatExploitStatus.UNPROVEN,
}


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CsafSchemaError(f"duplicate JSON key {key!r} in OASIS CSAF payload")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> Any:
    raise CsafSchemaError(f"non-finite JSON constant {token!r} in OASIS CSAF payload")


def _collect_product_branches(
    node: Mapping[str, Any],
    *,
    depth: int = 0,
    collected: dict[str, CsafProductBranch] | None = None,
) -> dict[str, CsafProductBranch]:
    if depth > _MAX_BRANCH_DEPTH:
        raise CsafSchemaError("OASIS CSAF product_tree exceeds maximum nesting depth")
    if collected is None:
        collected = {}
    product = node.get("product")
    if isinstance(product, Mapping):
        product_id = str(product.get("product_id") or "")
        name = str(product.get("name") or "")
        ident = product.get("product_identification_helper")
        cpe = str(ident.get("cpe")) if isinstance(ident, Mapping) and ident.get("cpe") else None
        branch = CsafProductBranch(product_id=product_id, name=name, cpe=cpe)
        if product_id in collected and collected[product_id] != branch:
            raise CsafSchemaError(f"conflicting product_tree entry for {product_id!r}")
        collected[product_id] = branch
    branches = node.get("branches")
    if branches is not None:
        if not isinstance(branches, list):
            raise CsafSchemaError("OASIS CSAF branches MUST be a list")
        for child in branches:
            if not isinstance(child, Mapping):
                raise CsafSchemaError("OASIS CSAF branch item MUST be an object")
            _collect_product_branches(child, depth=depth + 1, collected=collected)
    full_names = node.get("full_product_names")
    if full_names is not None:
        if not isinstance(full_names, list):
            raise CsafSchemaError("OASIS CSAF full_product_names MUST be a list")
        for item in full_names:
            if not isinstance(item, Mapping):
                raise CsafSchemaError("OASIS CSAF full_product_name item MUST be an object")
            _collect_product_branches({"product": item}, depth=depth + 1, collected=collected)
    return collected


def _parse_threats(threats_raw: object) -> tuple[CsafThreatExploitStatus, bool]:
    if threats_raw is None:
        return CsafThreatExploitStatus.UNPROVEN, False
    if not isinstance(threats_raw, list):
        raise CsafSchemaError("OASIS CSAF threats MUST be a list")
    rank = {
        CsafThreatExploitStatus.UNPROVEN: 0,
        CsafThreatExploitStatus.EXPLOITATION_UNLIKELY: 1,
        CsafThreatExploitStatus.EXPLOITATION_LESS_LIKELY: 2,
        CsafThreatExploitStatus.PUBLICLY_DISCLOSED: 3,
        CsafThreatExploitStatus.EXPLOITATION_MORE_LIKELY: 4,
        CsafThreatExploitStatus.EXPLOITED: 5,
    }
    best = CsafThreatExploitStatus.UNPROVEN
    disclosed = False
    for item in threats_raw:
        if not isinstance(item, Mapping):
            raise CsafSchemaError("OASIS CSAF threat entry MUST be an object")
        details = str(item.get("details") or "").strip().casefold()
        for clause in (part.strip() for part in details.split(";") if part.strip()):
            if ":" in clause:
                key, _, val = (segment.strip() for segment in clause.partition(":"))
                if key == "exploited":
                    if val == "yes":
                        best = CsafThreatExploitStatus.EXPLOITED
                        disclosed = True
                    elif val not in {"no", "false"}:
                        raise CsafSchemaError(f"invalid MSRC CSAF Exploited threat value {val!r}")
                elif key in {"publicly disclosed", "publicly_disclosed"}:
                    if val in {"yes", "true"}:
                        disclosed = True
                        if rank[CsafThreatExploitStatus.PUBLICLY_DISCLOSED] > rank[best]:
                            best = CsafThreatExploitStatus.PUBLICLY_DISCLOSED
                    elif val not in {"no", "false"}:
                        raise CsafSchemaError(f"invalid MSRC CSAF Publicly Disclosed value {val!r}")
                elif val in _EXPLOIT_STATUS_MAP:
                    mapped = _EXPLOIT_STATUS_MAP[val]
                    if rank[mapped] > rank[best]:
                        best = mapped
            elif clause in _EXPLOIT_STATUS_MAP:
                mapped = _EXPLOIT_STATUS_MAP[clause]
                if rank[mapped] > rank[best]:
                    best = mapped
                if mapped in {
                    CsafThreatExploitStatus.EXPLOITED,
                    CsafThreatExploitStatus.PUBLICLY_DISCLOSED,
                }:
                    disclosed = True
    return best, disclosed


def _parse_scores(
    scores_raw: object,
    *,
    allowed_products: frozenset[str],
) -> tuple[float, float | None, str, Severity]:
    if not isinstance(scores_raw, list) or not scores_raw:
        raise CsafSchemaError("OASIS CSAF vulnerability requires non-empty scores")
    highest_base = -1.0
    best_temporal: float | None = None
    best_vector = ""
    for item in scores_raw:
        if not isinstance(item, Mapping):
            raise CsafSchemaError("OASIS CSAF score entry MUST be an object")
        score_products = item.get("products")
        if score_products is not None:
            if (
                not isinstance(score_products, list)
                or not score_products
                or not all(isinstance(p, str) and p in allowed_products for p in score_products)
            ):
                raise CsafSchemaError(
                    "OASIS CSAF score products MUST reference vulnerability product_status ids"
                )
        cvss = item.get("cvss_v3")
        if not isinstance(cvss, Mapping):
            raise CsafSchemaError("OASIS CSAF score entry requires cvss_v3")
        base_raw = cvss.get("baseScore")
        if (
            not isinstance(base_raw, (int, float))
            or isinstance(base_raw, bool)
            or not math.isfinite(float(base_raw))
        ):
            raise CsafSchemaError("OASIS CSAF cvss_v3.baseScore MUST be a finite number")
        base_score = float(base_raw)
        vector = str(cvss.get("vectorString") or "")
        temporal_raw = cvss.get("temporalScore")
        temporal: float | None = None
        if temporal_raw is not None:
            if (
                not isinstance(temporal_raw, (int, float))
                or isinstance(temporal_raw, bool)
                or not math.isfinite(float(temporal_raw))
            ):
                raise CsafSchemaError("OASIS CSAF cvss_v3.temporalScore MUST be a finite number")
            temporal = float(temporal_raw)
        if base_score > highest_base:
            highest_base = base_score
            best_temporal = temporal
            best_vector = vector
    severity = severity_for_cvss_score(highest_base)
    return highest_base, best_temporal, best_vector, severity


def _parse_remediations(remediations_raw: object) -> tuple[CsafRemediationRecord, ...]:
    if remediations_raw is None:
        return ()
    if not isinstance(remediations_raw, list):
        raise CsafSchemaError("OASIS CSAF remediations MUST be a list")
    records: list[CsafRemediationRecord] = []
    for item in remediations_raw:
        if not isinstance(item, Mapping):
            raise CsafSchemaError("OASIS CSAF remediation entry MUST be an object")
        category = CsafRemediationCategory(str(item.get("category") or ""))
        prod_ids_raw = item.get("product_ids")
        if not isinstance(prod_ids_raw, Sequence) or isinstance(prod_ids_raw, (str, bytes)):
            raise CsafSchemaError("OASIS CSAF remediation product_ids MUST be a list")
        prod_ids = tuple(sorted({str(pid) for pid in prod_ids_raw}))
        records.append(
            CsafRemediationRecord(
                category=category,
                product_ids=prod_ids,
                details=str(item.get("details") or ""),
                fixed_version=(
                    str(item["fixed_version"]) if item.get("fixed_version") is not None else None
                ),
                kb_article=str(item["kb_article"]) if item.get("kb_article") is not None else None,
                workaround_property=(
                    str(item["workaround_property"])
                    if item.get("workaround_property") is not None
                    else None
                ),
                workaround_expected_value=item.get("workaround_expected_value"),
                recommended_action_type=(
                    str(item["recommended_action_type"])
                    if item.get("recommended_action_type") is not None
                    else None
                ),
                url=str(item["url"]) if item.get("url") is not None else None,
            )
        )
    return tuple(records)


def parse_oasis_csaf_bytes(
    raw_bytes: bytes,
    *,
    expected_sha256: str,
    signature_verified: bool,
    source_url: str,
) -> CsafAdvisoryDocument:
    """Parse and verify raw OASIS CSAF 2.0 JSON bytes into a CsafAdvisoryDocument."""

    if not raw_bytes or len(raw_bytes) > _MAX_RAW_CSAF_BYTES:
        raise CsafSchemaError("OASIS CSAF payload size is invalid or exceeds byte ceiling")
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise CsafSchemaError("expected_sha256 MUST be lowercase sha256:<64-hex>")
    actual_digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    if actual_digest != expected_sha256:
        raise CsafSchemaError("OASIS CSAF byte digest does not match expected_sha256")
    if not signature_verified:
        raise CsafSchemaError("OASIS CSAF advisory requires verified detached signature")
    try:
        payload: Any = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CsafSchemaError("OASIS CSAF payload is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise CsafSchemaError("OASIS CSAF root MUST be a JSON object")
    doc = payload.get("document")
    tree = payload.get("product_tree")
    vulns_raw = payload.get("vulnerabilities")
    if (
        not isinstance(doc, Mapping)
        or not isinstance(tree, Mapping)
        or not isinstance(vulns_raw, list)
    ):
        raise CsafSchemaError("OASIS CSAF requires document, product_tree, and vulnerabilities")
    publisher = doc.get("publisher")
    if publisher is not None:
        if not isinstance(publisher, Mapping):
            raise CsafSchemaError("OASIS CSAF document.publisher MUST be an object")
        namespace = str(publisher.get("namespace") or "")
        if namespace and not namespace.startswith("https://msrc.microsoft.com"):
            raise CsafSchemaError(
                "OASIS CSAF document.publisher.namespace MUST belong to https://msrc.microsoft.com"
            )
    tracking = doc.get("tracking")
    if not isinstance(tracking, Mapping):
        raise CsafSchemaError("OASIS CSAF document.tracking is required")
    rev_history = tracking.get("revision_history")
    if not isinstance(rev_history, list) or not rev_history:
        raise CsafSchemaError("OASIS CSAF document.tracking.revision_history MUST be non-empty")
    branches = _collect_product_branches(tree)
    products = tuple(branches[pid] for pid in sorted(branches))
    vulnerabilities: list[CsafVulnerabilityRecord] = []
    for vuln_item in vulns_raw:
        if not isinstance(vuln_item, Mapping):
            raise CsafSchemaError("OASIS CSAF vulnerability item MUST be an object")
        status = vuln_item.get("product_status")
        if not isinstance(status, Mapping):
            raise CsafSchemaError("OASIS CSAF vulnerability.product_status is required")
        known_affected = tuple(sorted({str(x) for x in (status.get("known_affected") or [])}))
        fixed = tuple(sorted({str(x) for x in (status.get("fixed") or [])}))
        not_affected = tuple(sorted({str(x) for x in (status.get("known_not_affected") or [])}))
        base_score, temporal_score, vector, severity = _parse_scores(
            vuln_item.get("scores"),
            allowed_products=frozenset(known_affected) | frozenset(fixed),
        )
        exploit_status, disclosed = _parse_threats(vuln_item.get("threats"))
        remediations = _parse_remediations(vuln_item.get("remediations"))
        vulnerabilities.append(
            CsafVulnerabilityRecord(
                cve_id=str(vuln_item.get("cve") or ""),
                title=str(vuln_item.get("title") or ""),
                cvss_base_score=base_score,
                cvss_temporal_score=temporal_score,
                cvss_vector=vector,
                severity=severity,
                exploit_status=exploit_status,
                publicly_disclosed=disclosed,
                known_affected_product_ids=known_affected,
                fixed_product_ids=fixed,
                known_not_affected_product_ids=not_affected,
                remediations=remediations,
            )
        )
    vulnerabilities.sort(key=lambda item: item.cve_id)
    return CsafAdvisoryDocument(
        csaf_version=str(doc.get("csaf_version") or ""),
        tracking_id=str(tracking.get("id") or ""),
        title=str(doc.get("title") or ""),
        initial_release_date=datetime.fromisoformat(
            str(tracking.get("initial_release_date") or "")
        ),
        current_release_date=datetime.fromisoformat(
            str(tracking.get("current_release_date") or "")
        ),
        revision_count=len(rev_history),
        source_url=source_url,
        document_digest=actual_digest,
        signature_verified=signature_verified,
        products=products,
        vulnerabilities=tuple(vulnerabilities),
    )


__all__ = ["parse_oasis_csaf_bytes"]
