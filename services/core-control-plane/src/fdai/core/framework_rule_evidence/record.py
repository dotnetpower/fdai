"""Build the persisted, versioned scoped Rule coverage record for one workload.

The record is the durable form of ``ScopedRuleCoverage``: it binds the workload scope, the
provider-id mapping, the activation pin, the inventory generation, and the version 2 baseline it
was projected from. Building it is pure; persistence belongs to the delivery adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdai_service_contracts.baseline_evaluation import BaselineEvaluationCoverage
from fdai_service_contracts.framework_rule_coverage import (
    ScopedRuleCoverageRecord,
    ScopedRuleCoverageResource,
    ScopedRuleCoverageRule,
    framework_rule_coverage_record_digest,
    scoped_rule_coverage_resource_set_digest,
    verify_scoped_rule_coverage_identity,
)

from fdai.rule_catalog.schema.framework_assessment import canonical_digest

from .coverage import ScopedRuleCoverage, baseline_ref

SCOPED_COVERAGE_AUDIT_KIND = "framework_rule_evidence.scoped_coverage"


@dataclass(frozen=True, slots=True)
class ScopedCoverageResourceMapping:
    """One workload resource with its provider id and neutral inventory id."""

    provider_resource_id: str
    resource_id: str
    resource_type: str


def build_scoped_coverage_record(
    *,
    framework_id: str,
    workload_id: str,
    scoped: ScopedRuleCoverage,
    resources: Sequence[ScopedCoverageResourceMapping],
    baseline: BaselineEvaluationCoverage,
) -> ScopedRuleCoverageRecord:
    """Return the content-addressed record for ``scoped`` and its baseline.

    Raises:
        ValueError: when the projection and baseline disagree on activation, catalog, or
            inventory identity, or when the provider-id mapping is ambiguous.
    """

    mapped = tuple(
        sorted(
            (
                ScopedRuleCoverageResource(
                    provider_resource_id=item.provider_resource_id,
                    resource_ref=baseline_ref("resource", item.resource_id),
                    resource_type=item.resource_type,
                )
                for item in resources
            ),
            key=lambda item: item.provider_resource_id,
        )
    )
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "framework_id": framework_id,
        "workload_id": workload_id,
        "scope_digest": scoped.scope_digest,
        "resource_set_digest": scoped_rule_coverage_resource_set_digest(mapped),
        "resources": mapped,
        "rule_activation_generation_id": scoped.activation.generation_id,
        "rule_activation_generation_digest": scoped.activation.generation_digest,
        "rule_catalog_digest": scoped.activation.rule_catalog_digest,
        "evaluated_rule_catalog_digest": baseline.evaluated_rule_catalog_digest,
        "dispatch_signal": scoped.dispatch_signal,
        "expected_pair_set_digest": baseline.expected_pair_set_digest,
        "inventory_generation": scoped.inventory_generation,
        "baseline_generation_id": baseline_ref("generation", scoped.inventory_generation),
        "inventory_observation_digest": baseline.inventory_observation_digest,
        "inventory_observed_at": scoped.inventory_observed_at,
        "recorded_at": scoped.recorded_at,
        "rules": tuple(
            ScopedRuleCoverageRule.model_validate(item.to_dict()) for item in scoped.rules
        ),
        "unattributed_unexpected_count": scoped.unattributed_unexpected_count,
        "scoped_coverage_digest": scoped.coverage_digest,
        "baseline_coverage_digest": baseline.coverage_digest,
        "baseline_audit_ref": baseline.audit_ref,
        "baseline_audit_digest": baseline.audit_digest,
        "projection_authority": False,
        "execution_authority": False,
    }
    audit_digest = canonical_digest(
        {
            "kind": SCOPED_COVERAGE_AUDIT_KIND,
            "scope_digest": scoped.scope_digest,
            "scoped_coverage_digest": scoped.coverage_digest,
            "baseline_coverage_digest": baseline.coverage_digest,
            "resource_set_digest": values["resource_set_digest"],
        }
    )
    values["audit_ref"] = "framework-rule-coverage:" + audit_digest.removeprefix("sha256:")[:32]
    values["audit_digest"] = audit_digest
    values["record_digest"] = framework_rule_coverage_record_digest(**values)
    record = ScopedRuleCoverageRecord.model_validate(values)
    verify_scoped_rule_coverage_identity(
        record,
        baseline=baseline,
        scope_digest=scoped.scope_digest,
        rule_activation_generation_digest=scoped.activation.generation_digest,
    )
    return record


__all__ = [
    "SCOPED_COVERAGE_AUDIT_KIND",
    "ScopedCoverageResourceMapping",
    "build_scoped_coverage_record",
]
