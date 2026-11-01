"""Deterministic shadow-only MSRC CSAF vulnerability assessment runtime."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from fdai.core.security.observations import (
    ApplicabilityStatus,
    ControlStatus,
    RemediationPriority,
    SecurityControlObservation,
)
from fdai.rule_catalog.schema.msrc_csaf import (
    CsafAdvisoryDocument,
    CsafDisposition,
    CsafProductCrosswalk,
    CsafSchemaError,
    CsafThreatExploitStatus,
    CsafVulnerabilityCrosswalk,
    CsafVulnerabilityRecord,
    MsrcCsafCrosswalkCatalog,
    compare_dotted_versions,
    parse_dotted_version,
    version_train_prefix,
)
from fdai.rule_catalog.schema.wara_assessment import (
    ResourceTypeDisposition,
    WaraMappingState,
    canonical_digest,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.projection import Severity as ProjectionSeverity

from .models import (
    CsafAssessmentRequest,
    CsafAssessmentResult,
    CsafEvaluationStatus,
    CsafEvidenceReceipt,
    CsafExposureStatus,
    CsafScopedResource,
    CsafVulnerabilityFinding,
)


def _strict_scalar_equal(left: object, right: object) -> bool:
    """Compare scalar values without treating bool as int (True != 1, False != 0)."""

    return type(left) is type(right) and left == right


def _index_evidence(
    receipts: Sequence[CsafEvidenceReceipt],
) -> dict[str, tuple[CsafEvidenceReceipt, ...]]:
    grouped: dict[str, list[CsafEvidenceReceipt]] = {}
    seen_refs: set[tuple[str, str]] = set()
    for receipt in receipts:
        key = (receipt.cve_id, receipt.evidence_ref)
        if key in seen_refs:
            raise ValueError(f"duplicate CSAF evidence receipt {key!r}")
        seen_refs.add(key)
        grouped.setdefault(receipt.cve_id, []).append(receipt)
    return {
        cve_id: tuple(sorted(items, key=lambda item: item.evidence_ref))
        for cve_id, items in grouped.items()
    }


def _validate_receipts(
    receipts: tuple[CsafEvidenceReceipt, ...],
    request: CsafAssessmentRequest,
    *,
    freshness_ceiling_seconds: int,
) -> tuple[tuple[CsafEvidenceReceipt, ...], tuple[str, ...]]:
    admitted: list[CsafEvidenceReceipt] = []
    reasons: set[str] = set()
    ceiling = timedelta(seconds=freshness_ceiling_seconds)
    for receipt in receipts:
        item_reasons: set[str] = set()
        if receipt.scope_digest != request.scope_digest:
            item_reasons.add("scope_mismatch")
        if receipt.source_revision != request.source_revision:
            item_reasons.add("source_revision_mismatch")
        if receipt.inventory_generation != request.inventory_generation:
            item_reasons.add("inventory_generation_mismatch")
        if receipt.synthetic:
            item_reasons.add("synthetic_evidence_rejected")
        if receipt.provider_error is not None:
            item_reasons.add("provider_error")
        if not receipt.complete:
            item_reasons.add("incomplete_evidence")
        if receipt.truncated:
            item_reasons.add("truncated_evidence")
        if receipt.conflicting:
            item_reasons.add("conflicting_evidence")
        if receipt.observed_at > request.evaluated_at:
            item_reasons.add("future_evidence_timestamp")
        elif request.evaluated_at - receipt.observed_at > timedelta(
            seconds=min(receipt.freshness_ceiling_seconds, ceiling.total_seconds())
        ):
            item_reasons.add("stale_evidence")
        reasons.update(item_reasons)
        if not item_reasons:
            admitted.append(receipt)
    outcomes = {item.outcome for item in admitted}
    if len(outcomes) > 1:
        reasons.add("conflicting_evidence_outcomes")
        return (), tuple(sorted(reasons))
    if reasons:
        return (), tuple(sorted(reasons))
    return tuple(admitted), ()


def _evaluate_resource_against_product(
    resource: CsafScopedResource,
    product: CsafProductCrosswalk,
    mapping: CsafVulnerabilityCrosswalk,
    request: CsafAssessmentRequest,
    *,
    receipt_outcome: CsafExposureStatus | None,
    has_receipt_limitations: bool,
) -> tuple[CsafExposureStatus, str | None, str]:
    if product.disposition is not ResourceTypeDisposition.CANONICAL:
        return CsafExposureStatus.UNKNOWN, "unsupported_product_mapping", ""
    if resource.observed_at > request.evaluated_at:
        return CsafExposureStatus.UNKNOWN, "future_resource_observation", ""
    if request.evaluated_at - resource.observed_at > timedelta(
        seconds=product.freshness_ceiling_seconds
    ):
        return CsafExposureStatus.UNKNOWN, "stale_resource_observation", ""
    prop_name = product.version_property
    if prop_name is None or prop_name not in resource.properties:
        return CsafExposureStatus.UNKNOWN, "missing_version_property", ""
    raw_version = resource.properties[prop_name]
    if not isinstance(raw_version, str):
        return CsafExposureStatus.UNKNOWN, "invalid_version_property_type", ""
    try:
        obs_tuple = parse_dotted_version(raw_version)
    except CsafSchemaError:
        return CsafExposureStatus.UNKNOWN, "malformed_version_property", ""
    min_ver = product.minimum_affected_version_inclusive
    max_ver = product.vulnerable_version_ceiling_exclusive
    if min_ver is None or max_ver is None:
        return CsafExposureStatus.UNKNOWN, "missing_product_version_window", ""
    ref = f"inventory:{resource.resource_id}:{prop_name}={raw_version}"
    train_prefix = version_train_prefix(min_ver, max_ver)
    if train_prefix and obs_tuple[: len(train_prefix)] != train_prefix:
        return CsafExposureStatus.NOT_APPLICABLE, None, ref
    if compare_dotted_versions(raw_version, min_ver) < 0:
        return CsafExposureStatus.NOT_APPLICABLE, None, ref
    if compare_dotted_versions(raw_version, max_ver) >= 0:
        if has_receipt_limitations or receipt_outcome in {
            CsafExposureStatus.AFFECTED,
            CsafExposureStatus.UNKNOWN,
        }:
            return CsafExposureStatus.UNKNOWN, "conflicting_inventory_and_receipt_outcome", ref
        return CsafExposureStatus.FIXED, None, ref
    if has_receipt_limitations or receipt_outcome is CsafExposureStatus.UNKNOWN:
        return CsafExposureStatus.UNKNOWN, None, ref
    if receipt_outcome in {CsafExposureStatus.FIXED, CsafExposureStatus.NOT_APPLICABLE}:
        return CsafExposureStatus.UNKNOWN, "conflicting_inventory_and_receipt_outcome", ref
    if receipt_outcome is CsafExposureStatus.AFFECTED:
        return CsafExposureStatus.AFFECTED, None, ref
    if (
        mapping.workaround_property is not None
        and mapping.workaround_expected_value is not None
        and _strict_scalar_equal(
            resource.properties.get(mapping.workaround_property),
            mapping.workaround_expected_value,
        )
    ) or receipt_outcome is CsafExposureStatus.MITIGATED:
        return CsafExposureStatus.MITIGATED, None, ref
    return CsafExposureStatus.AFFECTED, None, ref


class MsrcCsafAssessmentRuntime:
    """Evaluate pinned MSRC CSAF advisories and crosswalks deterministically in shadow mode."""

    def __init__(self, catalog: MsrcCsafCrosswalkCatalog) -> None:
        self._catalog = catalog
        self._products: dict[str, CsafProductCrosswalk] = {
            item.product_id: item for item in catalog.product_mappings
        }
        self._advisories: dict[str, CsafAdvisoryDocument] = {
            item.tracking_id: item for item in catalog.advisories
        }
        self._vulnerabilities: dict[str, CsafVulnerabilityRecord] = {
            vuln.cve_id: vuln
            for advisory in catalog.advisories
            for vuln in advisory.vulnerabilities
        }

    @property
    def catalog(self) -> MsrcCsafCrosswalkCatalog:
        return self._catalog

    def assess(self, request: CsafAssessmentRequest) -> CsafAssessmentResult:
        if request.source_revision != self._catalog.source_revision:
            raise ValueError("CSAF assessment source_revision mismatch")
        if request.crosswalk_digest != self._catalog.crosswalk_digest:
            raise ValueError("CSAF assessment crosswalk_digest mismatch")
        if request.advisories_digest != self._catalog.advisories_digest:
            raise ValueError("CSAF assessment advisories_digest mismatch")

        evidence_by_cve = _index_evidence(request.evidence)
        findings = tuple(
            self._evaluate_vulnerability(
                mapping,
                request,
                evidence_by_cve.get(mapping.cve_id, ()),
            )
            for mapping in self._catalog.vulnerability_mappings
        )
        counts: dict[str, int] = {}
        for finding in findings:
            for prefix, value in (
                ("disposition", finding.disposition.value),
                ("mapping", finding.mapping_state),
                ("evaluation", finding.evaluation.value),
                ("exposure", finding.exposure.value),
                ("severity", finding.severity.value),
                ("exploit_status", finding.exploit_status.value),
            ):
                key = f"{prefix}.{value}"
                counts[key] = counts.get(key, 0) + 1
            if (
                finding.exposure is CsafExposureStatus.AFFECTED
                and finding.exploit_status is CsafThreatExploitStatus.EXPLOITED
            ):
                counts["exploited_affected"] = counts.get("exploited_affected", 0) + 1

        digest_material: dict[str, Any] = {
            "assessment_id": request.assessment_id,
            "mode": "shadow",
            "execution_authority": False,
            "source_revision": request.source_revision,
            "crosswalk_digest": request.crosswalk_digest,
            "advisories_digest": request.advisories_digest,
            "ontology_release": request.ontology_release,
            "inventory_generation": request.inventory_generation,
            "workload_id": request.workload_id,
            "scope_digest": request.scope_digest,
            "evaluated_at": request.evaluated_at.isoformat(),
            "recorded_at": request.recorded_at.isoformat(),
            "findings": [item.to_dict() for item in findings],
            "aggregate_counts": dict(sorted(counts.items())),
        }
        return CsafAssessmentResult(
            assessment_id=request.assessment_id,
            mode="shadow",
            execution_authority=False,
            source_revision=request.source_revision,
            crosswalk_digest=request.crosswalk_digest,
            advisories_digest=request.advisories_digest,
            ontology_release=request.ontology_release,
            inventory_generation=request.inventory_generation,
            workload_id=request.workload_id,
            scope_digest=request.scope_digest,
            evaluated_at=request.evaluated_at,
            recorded_at=request.recorded_at,
            findings=findings,
            aggregate_counts=dict(sorted(counts.items())),
            result_digest=canonical_digest(digest_material),
        )

    def _evaluate_vulnerability(
        self,
        mapping: CsafVulnerabilityCrosswalk,
        request: CsafAssessmentRequest,
        receipts: tuple[CsafEvidenceReceipt, ...],
    ) -> CsafVulnerabilityFinding:
        vuln = self._vulnerabilities[mapping.cve_id]
        if (
            mapping.disposition is CsafDisposition.AMBIGUOUS_OR_BLOCKED
            or mapping.mapping_state is WaraMappingState.UNMAPPED
            or mapping.blocked_reasons
        ):
            reasons = mapping.blocked_reasons or ("unmapped_vulnerability",)
            return CsafVulnerabilityFinding(
                cve_id=mapping.cve_id,
                advisory_tracking_id=mapping.advisory_tracking_id,
                title=vuln.title,
                severity=vuln.severity,
                cvss_base_score=vuln.cvss_base_score,
                exploit_status=vuln.exploit_status,
                disposition=mapping.disposition,
                mapping_state=mapping.mapping_state.value,
                evaluation=CsafEvaluationStatus.BLOCKED,
                exposure=CsafExposureStatus.UNKNOWN,
                affected_resource_ids=(),
                mitigated_resource_ids=(),
                fixed_resource_ids=(),
                unknown_resource_ids=(),
                recommended_action_type=mapping.candidate_action_type,
                evidence_refs=(),
                evidence_digests=(),
                evidence_complete=False,
                limitations=reasons,
            )

        products = [self._products[pid] for pid in mapping.product_ids]
        freshness_ceiling = min(item.freshness_ceiling_seconds for item in products)
        admitted_receipts, receipt_limitations = _validate_receipts(
            receipts,
            request,
            freshness_ceiling_seconds=freshness_ceiling,
        )
        receipt_outcome: CsafExposureStatus | None = (
            admitted_receipts[0].outcome if admitted_receipts and not receipt_limitations else None
        )

        affected_ids: set[str] = set()
        mitigated_ids: set[str] = set()
        fixed_ids: set[str] = set()
        unknown_ids: set[str] = set()
        limitations: set[str] = set(receipt_limitations)
        evidence_refs: list[str] = [item.evidence_ref for item in admitted_receipts]
        evidence_digests: list[str] = [item.evidence_digest for item in admitted_receipts]
        matched_any_resource = False
        precedence = {
            CsafExposureStatus.AFFECTED: 4,
            CsafExposureStatus.UNKNOWN: 3,
            CsafExposureStatus.MITIGATED: 2,
            CsafExposureStatus.FIXED: 1,
            CsafExposureStatus.NOT_APPLICABLE: 0,
        }

        for resource in request.resources:
            rtype = resource.provider_resource_type.casefold()
            matching_products = [
                prod
                for prod in products
                if rtype in {pt.casefold() for pt in prod.provider_resource_types}
            ]
            if not matching_products:
                continue
            matched_any_resource = True
            resource_statuses: list[CsafExposureStatus] = []
            for prod in matching_products:
                status, limitation, ref = _evaluate_resource_against_product(
                    resource,
                    prod,
                    mapping,
                    request,
                    receipt_outcome=receipt_outcome,
                    has_receipt_limitations=bool(receipt_limitations),
                )
                if limitation is not None:
                    limitations.add(limitation)
                if ref:
                    evidence_refs.append(ref)
                    evidence_digests.append(canonical_digest({"ref": ref}))
                resource_statuses.append(status)
            non_na = [s for s in resource_statuses if s is not CsafExposureStatus.NOT_APPLICABLE]
            resolved = (
                max(non_na, key=lambda item: precedence[item])
                if non_na
                else CsafExposureStatus.NOT_APPLICABLE
            )
            if resolved is CsafExposureStatus.AFFECTED:
                affected_ids.add(resource.resource_id)
            elif resolved is CsafExposureStatus.UNKNOWN:
                unknown_ids.add(resource.resource_id)
            elif resolved is CsafExposureStatus.MITIGATED:
                mitigated_ids.add(resource.resource_id)
            elif resolved is CsafExposureStatus.FIXED:
                fixed_ids.add(resource.resource_id)

        if not matched_any_resource:
            return CsafVulnerabilityFinding(
                cve_id=mapping.cve_id,
                advisory_tracking_id=mapping.advisory_tracking_id,
                title=vuln.title,
                severity=vuln.severity,
                cvss_base_score=vuln.cvss_base_score,
                exploit_status=vuln.exploit_status,
                disposition=mapping.disposition,
                mapping_state=mapping.mapping_state.value,
                evaluation=CsafEvaluationStatus.EVALUATED,
                exposure=CsafExposureStatus.NOT_APPLICABLE,
                affected_resource_ids=(),
                mitigated_resource_ids=(),
                fixed_resource_ids=(),
                unknown_resource_ids=(),
                recommended_action_type=None,
                evidence_refs=(),
                evidence_digests=(),
                evidence_complete=True,
                limitations=(),
            )

        if affected_ids:
            overall = CsafExposureStatus.AFFECTED
        elif unknown_ids:
            overall = CsafExposureStatus.UNKNOWN
        elif mitigated_ids:
            overall = CsafExposureStatus.MITIGATED
        elif fixed_ids:
            overall = CsafExposureStatus.FIXED
        else:
            overall = CsafExposureStatus.NOT_APPLICABLE

        if mapping.mapping_state is WaraMappingState.PARTIAL and overall in {
            CsafExposureStatus.FIXED,
            CsafExposureStatus.MITIGATED,
        }:
            overall = CsafExposureStatus.UNKNOWN
            limitations.add("partial_mapping_requires_manual_verification")

        complete = not unknown_ids and not limitations and overall is not CsafExposureStatus.UNKNOWN
        return CsafVulnerabilityFinding(
            cve_id=mapping.cve_id,
            advisory_tracking_id=mapping.advisory_tracking_id,
            title=vuln.title,
            severity=vuln.severity,
            cvss_base_score=vuln.cvss_base_score,
            exploit_status=vuln.exploit_status,
            disposition=mapping.disposition,
            mapping_state=mapping.mapping_state.value,
            evaluation=CsafEvaluationStatus.EVALUATED,
            exposure=overall,
            affected_resource_ids=tuple(sorted(affected_ids)),
            mitigated_resource_ids=tuple(sorted(mitigated_ids)),
            fixed_resource_ids=tuple(sorted(fixed_ids)),
            unknown_resource_ids=tuple(sorted(unknown_ids)),
            recommended_action_type=(
                mapping.candidate_action_type
                if overall in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
                else None
            ),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            evidence_digests=tuple(dict.fromkeys(evidence_digests)),
            evidence_complete=complete,
            limitations=tuple(sorted(limitations)),
        )


def to_security_control_observations(
    result: CsafAssessmentResult,
) -> tuple[SecurityControlObservation, ...]:
    """Convert CSAF assessment findings into SecurityControlObservations for SecurityAssessment."""

    observations: list[SecurityControlObservation] = []
    status_map = {
        CsafExposureStatus.AFFECTED: ControlStatus.FAIL,
        CsafExposureStatus.MITIGATED: ControlStatus.WARNING,
        CsafExposureStatus.FIXED: ControlStatus.PASS,
        CsafExposureStatus.NOT_APPLICABLE: ControlStatus.NOT_APPLICABLE,
        CsafExposureStatus.UNKNOWN: ControlStatus.UNKNOWN,
    }
    priority_map = {
        Severity.CRITICAL: RemediationPriority.CRITICAL,
        Severity.HIGH: RemediationPriority.HIGH,
        Severity.MEDIUM: RemediationPriority.MEDIUM,
        Severity.LOW: RemediationPriority.LOW,
    }
    severity_literal: dict[Severity, ProjectionSeverity] = {
        Severity.LOW: "low",
        Severity.MEDIUM: "medium",
        Severity.HIGH: "high",
        Severity.CRITICAL: "critical",
    }
    for finding in result.findings:
        per_resource_pairs: list[tuple[str, CsafExposureStatus]] = [
            *[(rid, CsafExposureStatus.AFFECTED) for rid in finding.affected_resource_ids],
            *[(rid, CsafExposureStatus.UNKNOWN) for rid in finding.unknown_resource_ids],
            *[(rid, CsafExposureStatus.MITIGATED) for rid in finding.mitigated_resource_ids],
            *[(rid, CsafExposureStatus.FIXED) for rid in finding.fixed_resource_ids],
        ]
        if not per_resource_pairs:
            per_resource_pairs = [(f"workload://{result.workload_id}", finding.exposure)]
        for target_ref, resource_exposure in per_resource_pairs:
            applicability = (
                ApplicabilityStatus.NOT_APPLICABLE
                if resource_exposure is CsafExposureStatus.NOT_APPLICABLE
                else (
                    ApplicabilityStatus.UNKNOWN
                    if resource_exposure is CsafExposureStatus.UNKNOWN
                    else ApplicabilityStatus.APPLICABLE
                )
            )
            priority = (
                RemediationPriority.CRITICAL
                if finding.exploit_status is CsafThreatExploitStatus.EXPLOITED
                and resource_exposure is CsafExposureStatus.AFFECTED
                else (
                    priority_map[finding.severity]
                    if resource_exposure
                    in {CsafExposureStatus.AFFECTED, CsafExposureStatus.MITIGATED}
                    else RemediationPriority.NONE
                )
            )
            observations.append(
                SecurityControlObservation(
                    control_id=f"msrc-csaf:{finding.cve_id}:{target_ref}",
                    title=finding.title,
                    category="vulnerability_management",
                    resource_type="workload-scope",
                    resource_ref=target_ref,
                    status=status_map[resource_exposure],
                    severity=severity_literal[finding.severity],
                    current_value=resource_exposure.value,
                    expected_value="fixed",
                    rationale=(
                        f"MSRC CSAF advisory {finding.advisory_tracking_id} "
                        f"(CVSS {finding.cvss_base_score:.1f}, "
                        f"exploit={finding.exploit_status.value})"
                    ),
                    source="msrc_csaf",
                    collected_at=result.evaluated_at,
                    evidence_refs=finding.evidence_refs or (f"csaf-result:{result.result_digest}",),
                    remediation=finding.recommended_action_type or "apply_vendor_fix",
                    validation="re-observe resource version property >= fixed ceiling",
                    priority=priority,
                    due_days=2 if priority is RemediationPriority.CRITICAL else 14,
                    applicability=applicability,
                    cve_ids=(finding.cve_id,),
                    source_urls=(
                        f"https://msrc.microsoft.com/update-guide/vulnerability/{finding.cve_id}",
                    ),
                    patch_status=resource_exposure.value,
                )
            )
    return tuple(observations)


__all__ = [
    "MsrcCsafAssessmentRuntime",
    "to_security_control_observations",
]
