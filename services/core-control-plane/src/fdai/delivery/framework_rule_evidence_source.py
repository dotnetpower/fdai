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
from fdai_service_contracts.framework_rule_coverage import (
    FRAMEWORK_RULE_COVERAGE_LATEST_KEY,
    ScopedRuleCoverageRecord,
    framework_rule_coverage_record_key,
)
from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.core.framework_assessment import (
    FrameworkEvidenceReceipt,
    FrameworkRuleActivationPin,
)
from fdai.core.framework_rule_evidence import (
    SCOPED_COVERAGE_AUDIT_KIND,
    T0_RULE_EVALUATOR,
    ExpectedRulePair,
    ScopedCoverageResourceMapping,
    ScopedRuleCoverage,
    WorkloadRuleResource,
    activation_pin,
    baseline_ref,
    build_rule_requirement_receipts,
    build_scoped_coverage,
    build_scoped_coverage_record,
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
    SCOPE_MISMATCH = "scope_mismatch"


@dataclass(frozen=True, slots=True)
class WorkloadRuleEvidence:
    """The activation pin, Rule receipts, and scoped coverage record for one workload."""

    status: WorkloadRuleEvidenceStatus
    pin: FrameworkRuleActivationPin | None
    receipts: tuple[FrameworkEvidenceReceipt, ...] = ()
    coverage_record: ScopedRuleCoverageRecord | None = None


@dataclass(frozen=True, slots=True)
class ScopedRuleCoverageLoad:
    """Scoped coverage of one exact workload scope, or the status explaining its absence."""

    status: WorkloadRuleEvidenceStatus
    pin: FrameworkRuleActivationPin | None
    scoped: ScopedRuleCoverage | None = None
    record: ScopedRuleCoverageRecord | None = None


async def load_scoped_rule_coverage(
    *,
    state_store: StateStore,
    activation: RuleActivationGeneration | None,
    scope: WaraResolvedScope,
    framework_id: str,
    scope_digest: str,
    evaluated_at: datetime,
    max_outcomes: int = 100_000,
) -> ScopedRuleCoverageLoad:
    """Project Forseti's verified version 2 baseline onto one workload scope.

    Any missing, incomplete, unverifiable, or mismatched baseline yields an explicit status and
    no coverage. ``scope_digest`` is the assessing framework's own scope identity.
    """

    if activation is None:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.NO_ACTIVATION, None)
    pin = activation_pin(activation)
    raw = await state_store.read_state(BASELINE_EVALUATION_LATEST_COVERAGE_KEY)
    if raw is None:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.NO_BASELINE, pin)
    coverage = BaselineEvaluationCoverage.model_validate(raw)
    if coverage.rule_activation_generation_digest != pin.generation_digest:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.BASELINE_ACTIVATION_DRIFT, pin)
    if coverage.generation_id != baseline_ref("generation", scope.inventory_generation):
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.BASELINE_GENERATION_MISMATCH, pin)
    if not coverage.complete:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.BASELINE_INCOMPLETE, pin)
    outcomes = await _workload_outcomes(
        state_store,
        coverage=coverage,
        max_outcomes=max_outcomes,
    )
    if outcomes is None:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.BASELINE_TOO_LARGE, pin)
    if _outcome_set_digest(outcomes) != coverage.outcome_set_digest:
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.BASELINE_OUTCOMES_UNVERIFIED, pin)
    if _ambiguous_mapping(scope):
        return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.SCOPE_MISMATCH, pin)
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
        scope_digest=scope_digest,
        resources=resources,
        expected_pairs=_expected_pairs(outcomes, resources=resources, activation=activation),
        outcomes=outcomes,
        activation=activation,
        requested_rule_ids=(),
        inventory_generation=scope.inventory_generation,
        inventory_observed_at=coverage.completed_at,
        recorded_at=max(evaluated_at, coverage.completed_at),
    )
    record = build_scoped_coverage_record(
        framework_id=framework_id,
        workload_id=scope.workload_id,
        scoped=scoped,
        resources=tuple(
            ScopedCoverageResourceMapping(
                provider_resource_id=item.provider_resource_id,
                resource_id=item.neutral_resource_id,
                resource_type=item.provider_resource_type,
            )
            for item in scope.resources
        ),
        baseline=coverage,
    )
    return ScopedRuleCoverageLoad(WorkloadRuleEvidenceStatus.READY, pin, scoped, record)


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

    loaded = await load_scoped_rule_coverage(
        state_store=state_store,
        activation=activation,
        scope=scope,
        framework_id=catalog.framework_id,
        scope_digest=profile_scope_digest,
        evaluated_at=evaluated_at,
        max_outcomes=max_outcomes,
    )
    if loaded.scoped is None or loaded.pin is None:
        return WorkloadRuleEvidence(loaded.status, loaded.pin)
    receipts = build_rule_requirement_receipts(
        catalog=catalog,
        coverage=loaded.scoped,
        profile_scope_digest=profile_scope_digest,
        pinned_activation=loaded.pin,
        evaluated_at=evaluated_at,
        source_identity=source_identity,
    )
    return WorkloadRuleEvidence(loaded.status, loaded.pin, receipts, loaded.record)


async def persist_scoped_rule_coverage(
    state_store: StateStore,
    record: ScopedRuleCoverageRecord,
) -> bool:
    """Persist one immutable scoped coverage record with its audit entry, then the pointer.

    The record and its audit entry are written atomically and only once per record digest, so a
    rerun of the same assessment appends no duplicate audit. The latest pointer always moves to
    the record of the most recent assessment. Returns whether the record was newly created.
    """

    value = record.model_dump(mode="json")
    created = await state_store.write_state_with_audit_if_absent(
        framework_rule_coverage_record_key(record.record_digest),
        value,
        {
            "action_kind": SCOPED_COVERAGE_AUDIT_KIND,
            "producer_principal": T0_RULE_EVALUATOR,
            "audit_ref": record.audit_ref,
            "audit_digest": record.audit_digest,
            "payload": {
                "framework_id": record.framework_id,
                "record_digest": record.record_digest,
                "scope_digest": record.scope_digest,
                "scoped_coverage_digest": record.scoped_coverage_digest,
                "baseline_coverage_digest": record.baseline_coverage_digest,
                "rule_activation_generation_id": record.rule_activation_generation_id,
                "rule_count": len(record.rules),
                "resource_count": len(record.resources),
            },
            "execution_authority": False,
        },
    )
    await state_store.write_state(FRAMEWORK_RULE_COVERAGE_LATEST_KEY, value)
    return created


def _ambiguous_mapping(scope: WaraResolvedScope) -> bool:
    """Whether one provider id or one inventory reference maps to more than one resource."""

    provider_ids = [item.provider_resource_id for item in scope.resources]
    resource_refs = [baseline_ref("resource", item.neutral_resource_id) for item in scope.resources]
    return len(set(provider_ids)) != len(provider_ids) or len(set(resource_refs)) != len(
        resource_refs
    )


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
            # Same Rule contents under another activation share a catalog digest, so the
            # pinned evaluation time and observation separate the two outcome sets.
            if (
                outcome.catalog_revision == coverage.evaluated_rule_catalog_digest
                and outcome.evaluated_at == coverage.completed_at
                and outcome.inventory_observation_digest == coverage.inventory_observation_digest
            ):
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
    "ScopedRuleCoverageLoad",
    "load_scoped_rule_coverage",
    "WorkloadRuleEvidence",
    "WorkloadRuleEvidenceStatus",
    "load_workload_rule_evidence",
    "persist_scoped_rule_coverage",
]
