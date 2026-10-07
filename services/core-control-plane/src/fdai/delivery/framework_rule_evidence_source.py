"""Project Forseti's complete version 2 baseline onto one framework workload, read-only.

A complete version 2 coverage record proves that the recorded outcomes equal the T0 dispatch
pair set for the whole inventory generation, so the workload subset of those outcomes is the
exact workload pair set. Any other state yields no Rule receipts and an explicit status, which
leaves Rule requirements ``unknown``. Nothing here evaluates a Rule or grants authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCoverage,
    BaselineEvaluationOutcome,
)
from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.core.framework_assessment import (
    FrameworkEvidenceReceipt,
    FrameworkRuleActivationPin,
)
from fdai.core.framework_rule_evidence import (
    ExpectedRulePair,
    WorkloadRuleResource,
    activation_pin,
    baseline_ref,
    build_rule_requirement_receipts,
    build_scoped_coverage,
    canonical_sha256,
)
from fdai.delivery.persistence.postgres_wara_scope import WaraResolvedScope
from fdai.rule_catalog.schema.framework_assessment import FrameworkAssessmentCatalog
from fdai.shared.providers.state_store import StateStore

BASELINE_EVALUATION_LATEST_COVERAGE_KEY = "baseline-evaluation:latest:coverage"
BASELINE_EVALUATION_OUTCOME_PREFIX = "baseline-evaluation:outcomes:"
_PAGE_SIZE = 1_000


class WorkloadRuleEvidenceStatus(StrEnum):
    """Why Rule receipts were or were not produced for one workload pass."""

    READY = "ready"
    NO_ACTIVATION = "no_activation"
    NO_BASELINE = "no_baseline"
    BASELINE_ACTIVATION_DRIFT = "baseline_activation_drift"
    BASELINE_GENERATION_MISMATCH = "baseline_generation_mismatch"
    BASELINE_INCOMPLETE = "baseline_incomplete"
    BASELINE_TOO_LARGE = "baseline_too_large"
    BASELINE_OUTCOMES_UNVERIFIED = "baseline_outcomes_unverified"


@dataclass(frozen=True, slots=True)
class WorkloadRuleEvidence:
    """The activation pin and Rule receipts for one workload profile."""

    status: WorkloadRuleEvidenceStatus
    pin: FrameworkRuleActivationPin | None
    receipts: tuple[FrameworkEvidenceReceipt, ...] = ()


async def load_workload_rule_evidence(
    *,
    state_store: StateStore,
    activation: RuleActivationGeneration | None,
    scope: WaraResolvedScope,
    catalog: FrameworkAssessmentCatalog,
    profile_scope_digest: str,
    evaluated_at: datetime,
    source_identity: str,
    max_outcomes: int = 100_000,
) -> WorkloadRuleEvidence:
    """Return the workload's Rule receipts, or an explicit status without receipts."""

    if activation is None:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.NO_ACTIVATION, None)
    pin = activation_pin(activation)
    raw = await state_store.read_state(BASELINE_EVALUATION_LATEST_COVERAGE_KEY)
    if raw is None:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.NO_BASELINE, pin)
    coverage = BaselineEvaluationCoverage.model_validate(raw)
    if coverage.rule_activation_generation_digest != pin.generation_digest:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.BASELINE_ACTIVATION_DRIFT, pin)
    if coverage.generation_id != baseline_ref("generation", scope.inventory_generation):
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.BASELINE_GENERATION_MISMATCH, pin)
    if not coverage.complete:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.BASELINE_INCOMPLETE, pin)
    outcomes = await _workload_outcomes(
        state_store,
        coverage=coverage,
        max_outcomes=max_outcomes,
    )
    if outcomes is None:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.BASELINE_TOO_LARGE, pin)
    if _outcome_set_digest(outcomes) != coverage.outcome_set_digest:
        return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.BASELINE_OUTCOMES_UNVERIFIED, pin)
    workload_refs = {baseline_ref("resource", item.neutral_resource_id) for item in scope.resources}
    outcomes = tuple(item for item in outcomes if item.resource_ref in workload_refs)
    resources = tuple(
        WorkloadRuleResource(
            resource_id=item.neutral_resource_id,
            resource_type=item.provider_resource_type,
        )
        for item in scope.resources
    )
    scoped = build_scoped_coverage(
        scope_digest=profile_scope_digest,
        resources=resources,
        expected_pairs=_expected_pairs(outcomes, resources=resources, activation=activation),
        outcomes=outcomes,
        activation=activation,
        requested_rule_ids=(),
        inventory_generation=scope.inventory_generation,
        inventory_observed_at=coverage.completed_at,
        recorded_at=max(evaluated_at, coverage.completed_at),
    )
    receipts = build_rule_requirement_receipts(
        catalog=catalog,
        coverage=scoped,
        profile_scope_digest=profile_scope_digest,
        pinned_activation=pin,
        evaluated_at=evaluated_at,
        source_identity=source_identity,
    )
    return WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.READY, pin, receipts)


async def _workload_outcomes(
    state_store: StateStore,
    *,
    coverage: BaselineEvaluationCoverage,
    max_outcomes: int,
) -> tuple[BaselineEvaluationOutcome, ...] | None:
    """Read every outcome of the covered generation and catalog, deduplicated by digest."""

    selected: dict[str, BaselineEvaluationOutcome] = {}
    offset = 0
    while True:
        rows, total = await state_store.read_state_page(
            BASELINE_EVALUATION_OUTCOME_PREFIX,
            limit=_PAGE_SIZE,
            offset=offset,
            field="generation_id",
            value=coverage.generation_id,
        )
        if total > max_outcomes:
            return None
        for row in rows:
            outcome = BaselineEvaluationOutcome.model_validate(row)
            if outcome.catalog_revision == coverage.evaluated_rule_catalog_digest:
                selected[outcome.outcome_digest] = outcome
        offset += len(rows)
        if not rows or offset >= total:
            return tuple(selected.values())


def _outcome_set_digest(outcomes: tuple[BaselineEvaluationOutcome, ...]) -> str:
    ordered = sorted(outcomes, key=lambda item: (item.resource_ref, item.rule_ref))
    encoded = json.dumps(
        [item.outcome_digest for item in ordered], sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expected_pairs(
    outcomes: tuple[BaselineEvaluationOutcome, ...],
    *,
    resources: tuple[WorkloadRuleResource, ...],
    activation: RuleActivationGeneration,
) -> tuple[ExpectedRulePair, ...]:
    resource_ids = {
        baseline_ref("resource", item.resource_id): item.resource_id for item in resources
    }
    rule_ids = {
        baseline_ref("rule", member.rule_id): member.rule_id for member in activation.members
    }
    pairs = {
        (resource_ids[outcome.resource_ref], rule_ids[outcome.rule_ref]): canonical_sha256(
            outcome.rule_revision
        )
        for outcome in outcomes
        if outcome.rule_ref in rule_ids
    }
    return tuple(
        ExpectedRulePair(resource_id=resource_id, rule_id=rule_id, evaluated_rule_digest=digest)
        for (resource_id, rule_id), digest in sorted(pairs.items(), key=lambda item: item[0][::-1])
    )


__all__ = [
    "WorkloadRuleEvidence",
    "WorkloadRuleEvidenceStatus",
    "load_workload_rule_evidence",
]
