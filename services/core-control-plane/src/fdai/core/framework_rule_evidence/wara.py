"""Produce WARA evidence receipts from scoped Rule coverage through reviewed exact bindings.

A receipt is decisive only when the binding's Rule revision is the activated member, every
eligible pair of the workload has exactly one terminal outcome at that revision, and at least one
resource is eligible. Anything else yields no receipt, which keeps the recommendation ``unknown``.
"""

from __future__ import annotations

from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.core.wara.models import WaraEvidenceReceipt, WaraSatisfactionStatus
from fdai.rule_catalog.schema.framework_assessment import canonical_digest
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog
from fdai.rule_catalog.schema.wara_rule_binding import WaraRuleBindingCatalog

from .coverage import RuleCoverage, ScopedRuleCoverage, canonical_sha256


def build_wara_rule_receipts(
    *,
    bindings: WaraRuleBindingCatalog,
    catalog: WaraAssessmentCatalog,
    coverage: ScopedRuleCoverage,
    activation: RuleActivationGeneration,
    scope_digest: str,
) -> tuple[WaraEvidenceReceipt, ...]:
    """Return one receipt per binding whose Rule coverage is decisive for this workload."""

    if coverage.scope_digest != scope_digest or coverage.unattributed_unexpected_count:
        return ()
    if coverage.activation.generation_digest != canonical_sha256(activation.generation_digest):
        return ()
    records = {record.aprl_guid: record for record in catalog.recommendations}
    members = {member.rule_id: member for member in activation.members}
    receipts: list[WaraEvidenceReceipt] = []
    for binding in bindings.bindings:
        record = records.get(binding.aprl_guid)
        member = members.get(binding.rule_id)
        rule = coverage.rule(binding.rule_id)
        if (
            record is None
            or record.query_review is None
            or member is None
            or member.rule_version != binding.rule_version
            or canonical_sha256(member.rule_digest) != binding.rule_digest
            or rule is None
        ):
            continue
        outcome = _decisive_outcome(rule, canonical_sha256(member.rule_digest))
        if outcome is None:
            continue
        evidence_digest = canonical_digest(
            {
                "binding": binding.model_dump(mode="json"),
                "coverage_digest": coverage.coverage_digest,
                "rule": rule.to_dict(),
                "outcome": outcome.value,
            }
        )
        receipts.append(
            WaraEvidenceReceipt(
                recommendation_id=binding.aprl_guid,
                evidence_ref=f"t0-rule-evidence:{evidence_digest.removeprefix('sha256:')}",
                evidence_kind="rule",
                producer=binding.evaluator_ref,
                scope_digest=scope_digest,
                source_revision=catalog.source_revision,
                inventory_generation=coverage.inventory_generation,
                observed_at=coverage.inventory_observed_at,
                recorded_at=coverage.recorded_at,
                evidence_digest=evidence_digest,
                freshness_ceiling_seconds=record.query_review.evidence_freshness_ceiling_seconds,
                complete=True,
                truncated=False,
                conflicting=False,
                synthetic=False,
                provider_error=None,
                outcome=outcome,
            )
        )
    return tuple(sorted(receipts, key=lambda item: item.recommendation_id))


def _decisive_outcome(
    rule: RuleCoverage,
    member_digest: str,
) -> WaraSatisfactionStatus | None:
    if (
        rule.member_rule_digest != member_digest
        or rule.evaluated_rule_digest != member_digest
        or rule.revision_mismatch_count
        or rule.missing_count
        or rule.duplicate_count
        or rule.conflicting_count
        or rule.unexpected_count
        or rule.eligible_count == 0
    ):
        return None
    if rule.violated_count:
        return WaraSatisfactionStatus.FAILED
    if rule.abstained_count:
        return None
    return WaraSatisfactionStatus.SATISFIED


__all__ = ["build_wara_rule_receipts"]
