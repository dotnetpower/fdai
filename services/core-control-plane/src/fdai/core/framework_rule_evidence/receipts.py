"""Map scoped Rule coverage to framework evidence receipts in a fixed precedence order."""

from __future__ import annotations

from datetime import datetime, timedelta

from fdai.core.framework_assessment import (
    FrameworkEvidenceReceipt,
    FrameworkRuleActivationPin,
    FrameworkRuleProvenance,
    FrameworkSatisfactionStatus,
)
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkRequirementKind,
    canonical_digest,
)

from .coverage import T0_RULE_EVALUATOR, RuleEvidenceLimitation, ScopedRuleCoverage

_Outcome = tuple[FrameworkSatisfactionStatus, RuleEvidenceLimitation | None]


def rule_requirement_outcome(
    *,
    coverage: ScopedRuleCoverage,
    rule_id: str,
    profile_scope_digest: str,
    pinned_activation: FrameworkRuleActivationPin,
    evaluated_at: datetime,
    freshness_ceiling_seconds: int,
) -> _Outcome:
    """Return the outcome of the first matching row of the ordered outcome table."""

    unknown = FrameworkSatisfactionStatus.UNKNOWN
    if coverage.scope_digest != profile_scope_digest:
        return unknown, RuleEvidenceLimitation.SCOPE_MISMATCH
    rule = coverage.rule(rule_id)
    if rule is None or rule.member_rule_digest is None:
        return unknown, RuleEvidenceLimitation.RULE_NOT_ACTIVATED
    if coverage.activation != pinned_activation:
        return unknown, RuleEvidenceLimitation.ACTIVATION_CATALOG_DRIFT
    if rule.revision_mismatch_count or (
        rule.eligible_count and rule.evaluated_rule_digest != rule.member_rule_digest
    ):
        return unknown, RuleEvidenceLimitation.RULE_REVISION_DRIFT
    if coverage.inventory_observed_at + timedelta(seconds=freshness_ceiling_seconds) <= (
        evaluated_at
    ):
        return unknown, RuleEvidenceLimitation.STALE_INVENTORY
    if rule.missing_count:
        return unknown, RuleEvidenceLimitation.PAIR_MISSING
    if rule.duplicate_count:
        return unknown, RuleEvidenceLimitation.DUPLICATE_PAIR
    if rule.conflicting_count:
        return unknown, RuleEvidenceLimitation.CONFLICTING_PAIR
    if rule.unexpected_count or coverage.unattributed_unexpected_count:
        return unknown, RuleEvidenceLimitation.UNEXPECTED_PAIR
    if rule.eligible_count == 0:
        return unknown, RuleEvidenceLimitation.NO_ELIGIBLE_RESOURCE
    if rule.violated_count:
        return FrameworkSatisfactionStatus.FAILED, None
    if rule.abstained_count:
        return unknown, RuleEvidenceLimitation.HELD_FOR_REVIEW
    return FrameworkSatisfactionStatus.SATISFIED, None


def build_rule_requirement_receipts(
    *,
    catalog: FrameworkAssessmentCatalog,
    coverage: ScopedRuleCoverage,
    profile_scope_digest: str,
    pinned_activation: FrameworkRuleActivationPin,
    evaluated_at: datetime,
    source_identity: str,
) -> tuple[FrameworkEvidenceReceipt, ...]:
    """Emit one ``t0-rule-evaluator`` receipt for every Rule requirement in the catalog."""

    receipts: list[FrameworkEvidenceReceipt] = []
    for control in catalog.controls:
        for requirement in control.evidence:
            if (
                requirement.kind is not FrameworkRequirementKind.RULE
                or requirement.authoritative_producer != T0_RULE_EVALUATOR
            ):
                continue
            rule_id = requirement.source_ref
            outcome, limitation = rule_requirement_outcome(
                coverage=coverage,
                rule_id=rule_id,
                profile_scope_digest=profile_scope_digest,
                pinned_activation=pinned_activation,
                evaluated_at=evaluated_at,
                freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
            )
            rule = coverage.rule(rule_id)
            evidence_digest = canonical_digest(
                {
                    "coverage_digest": coverage.coverage_digest,
                    "rule": rule.to_dict() if rule is not None else {"rule_id": rule_id},
                    "outcome": outcome.value,
                    "limitation": limitation.value if limitation is not None else None,
                }
            )
            receipts.append(
                FrameworkEvidenceReceipt(
                    framework_id=catalog.framework_id,
                    control_id=control.control_id,
                    requirement_id=requirement.requirement_id,
                    evidence_ref=f"t0-rule-evidence:{evidence_digest.removeprefix('sha256:')}",
                    evidence_kind=requirement.kind.value,
                    producer=T0_RULE_EVALUATOR,
                    source_identity=source_identity,
                    scope_digest=coverage.scope_digest,
                    observed_at=coverage.inventory_observed_at,
                    recorded_at=coverage.recorded_at,
                    evidence_digest=evidence_digest,
                    freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
                    complete=limitation
                    not in {
                        RuleEvidenceLimitation.PAIR_MISSING,
                        RuleEvidenceLimitation.DUPLICATE_PAIR,
                        RuleEvidenceLimitation.UNEXPECTED_PAIR,
                    },
                    truncated=False,
                    conflicting=limitation is RuleEvidenceLimitation.CONFLICTING_PAIR,
                    synthetic=False,
                    provider_error=None,
                    outcome=outcome,
                    evidence_role=requirement.evidence_role,
                    process_phase=requirement.process_phase,
                    inventory_generation=coverage.inventory_generation,
                    rule_provenance=FrameworkRuleProvenance(
                        activation=coverage.activation,
                        member_rule_digest=rule.member_rule_digest if rule is not None else None,
                        coverage_digest=coverage.coverage_digest,
                    ),
                    limitations=(limitation.value,) if limitation is not None else (),
                )
            )
    return tuple(sorted(receipts, key=lambda item: (item.control_id, item.requirement_id)))


__all__ = ["build_rule_requirement_receipts", "rule_requirement_outcome"]
