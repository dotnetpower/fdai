"""Fail-closed tests for T0 Rule evidence feeding framework assessments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.agents import (
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    BaselineEvaluationAuditReference,
    record_baseline_evaluation,
)
from fdai.core.framework_assessment import (
    FrameworkApplicabilityDecision,
    FrameworkApplicabilityStatus,
    FrameworkAssessmentProfile,
    FrameworkAssessmentRequest,
    FrameworkAssessmentResult,
    FrameworkAssessmentRuntime,
    FrameworkEvidenceReceipt,
    FrameworkOwnerBinding,
    FrameworkRuleActivationPin,
    FrameworkSatisfactionStatus,
)
from fdai.core.framework_rule_evidence import (
    RuleEvidenceLimitation,
    ScopedRuleCoverage,
    WorkloadRuleResource,
    activation_pin,
    baseline_ref,
    build_rule_requirement_receipts,
    build_scoped_coverage,
    canonical_sha256,
    expected_rule_pairs,
    rule_requirement_outcome,
)
from fdai.core.rule_activation.generation import build_rule_activation_generation, rule_digest
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkRequirementKind,
    FrameworkScopeKind,
    canonical_digest,
    load_framework_assessment_catalog,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_evaluation import BaselineEvaluationOutcome
from fdai_service_contracts.rule_activation import RuleActivationGeneration

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
GENERATION = "generation-1"
SCOPE_DIGEST = canonical_digest({"workload_id": "workload-1"})
CATALOG_REVISION = "sha256:" + "c" * 64
UNKNOWN = FrameworkSatisfactionStatus.UNKNOWN


class _Evaluator:
    def __init__(self, results: Mapping[str, PolicyResult | None]) -> None:
        self.results = dict(results)

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        del resource_props
        return self.results.get(rule.id, PolicyResult(denied=False, context={}))


async def _audit_binder(record: Mapping[str, Any]) -> BaselineEvaluationAuditReference:
    digest = canonical_digest({"record": repr(sorted(record.items()))})
    return BaselineEvaluationAuditReference(ref="audit:" + digest[7:39], digest=digest)


def _rule(
    rule_id: str,
    *,
    resource_type: str = "cache",
    triggered_by: tuple[str, ...] = ("inventory.resource_observed",),
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.RELIABILITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediation/example.tftpl"),
        remediates="remediate.example",
        triggered_by=list(triggered_by),
        provenance=Provenance(
            source_url="https://example.com/rule",
            resolved_ref="0" * 40,
            content_hash="sha256:example",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=NOW,
        ),
    )


def _activation(*rules: Rule) -> RuleActivationGeneration:
    return build_rule_activation_generation(
        rules,
        profile_id="framework-test",
        profile_version="1.0.0",
        created_at=NOW - timedelta(days=1),
    )


async def _baseline(
    rules: tuple[Rule, ...],
    resources: tuple[ResourceRecord, ...],
    results: Mapping[str, PolicyResult | None] | None = None,
) -> tuple[BaselineEvaluationOutcome, ...]:
    store = InMemoryStateStore()
    await record_baseline_evaluation(
        observation=PromotedInventoryObservation(
            generation=GENERATION,
            resources=resources,
            links=(),
            complete=True,
            recorded_at=NOW,
        ),
        engine=T0Engine(index=RuleIndex.build(rules), evaluator=_Evaluator(results or {})),
        rules=rules,
        catalog_revision=CATALOG_REVISION,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )
    rows, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=100)
    return tuple(BaselineEvaluationOutcome.model_validate(row) for row in rows)


def _resources(*items: tuple[str, str]) -> tuple[ResourceRecord, ...]:
    return tuple(
        ResourceRecord(resource_id=resource_id, type=resource_type, last_seen=NOW.isoformat())
        for resource_id, resource_type in items
    )


def _workload(records: tuple[ResourceRecord, ...]) -> tuple[WorkloadRuleResource, ...]:
    return tuple(
        WorkloadRuleResource(resource_id=item.resource_id, resource_type=item.type)
        for item in records
    )


async def _coverage(
    rules: tuple[Rule, ...],
    records: tuple[ResourceRecord, ...],
    *,
    results: Mapping[str, PolicyResult | None] | None = None,
    activation: RuleActivationGeneration | None = None,
    requested: tuple[str, ...] = (),
    outcomes: tuple[BaselineEvaluationOutcome, ...] | None = None,
    workload: tuple[ResourceRecord, ...] | None = None,
) -> ScopedRuleCoverage:
    scoped = _workload(workload if workload is not None else records)
    return build_scoped_coverage(
        scope_digest=SCOPE_DIGEST,
        resources=scoped,
        expected_pairs=expected_rule_pairs(resources=scoped, index=RuleIndex.build(rules)),
        outcomes=outcomes if outcomes is not None else await _baseline(rules, records, results),
        activation=activation or _activation(*rules),
        requested_rule_ids=requested,
        inventory_generation=GENERATION,
        inventory_observed_at=NOW - timedelta(minutes=5),
        recorded_at=NOW - timedelta(minutes=4),
    )


def _outcome(
    coverage: ScopedRuleCoverage,
    rule_id: str,
    *,
    scope_digest: str = SCOPE_DIGEST,
    pin: FrameworkRuleActivationPin | None = None,
    evaluated_at: datetime = NOW,
) -> tuple[FrameworkSatisfactionStatus, RuleEvidenceLimitation | None]:
    return rule_requirement_outcome(
        coverage=coverage,
        rule_id=rule_id,
        profile_scope_digest=scope_digest,
        pinned_activation=pin or coverage.activation,
        evaluated_at=evaluated_at,
        freshness_ceiling_seconds=86_400,
    )


@pytest.mark.asyncio
async def test_expected_pairs_match_forseti_t0_dispatch() -> None:
    rules = (
        _rule("cache.zone-redundant"),
        _rule("cache.other-signal", triggered_by=("change.applied",)),
        _rule("sql.backup", resource_type="sql-database"),
    )
    records = _resources(("cache-1", "cache"), ("cache-2", "cache"), ("sql-1", "sql-database"))

    expected = expected_rule_pairs(resources=_workload(records), index=RuleIndex.build(rules))
    outcomes = await _baseline(rules, records)

    expected_keys = {
        (baseline_ref("resource", pair.resource_id), baseline_ref("rule", pair.rule_id))
        for pair in expected
    }
    assert expected_keys == {(item.resource_ref, item.rule_ref) for item in outcomes}
    assert ("resource:cache-1", "rule:cache.other-signal") not in expected_keys


@pytest.mark.asyncio
async def test_identity_helpers_match_forseti_records() -> None:
    rule = _rule("cache.zone-redundant")
    long_id = "x" * 200
    (outcome,) = await _baseline(
        (rule,),
        (ResourceRecord(resource_id=long_id, type=rule.resource_type, props={}),),
    )
    assert baseline_ref("resource", long_id) == outcome.resource_ref
    assert baseline_ref("rule", rule.id) == outcome.rule_ref
    assert canonical_sha256(rule_digest(rule)) == outcome.rule_revision
    with pytest.raises(ValueError, match="SHA-256"):
        canonical_sha256("sha256:not-a-digest")


@pytest.mark.asyncio
async def test_complete_compliant_and_violated_coverage_decides_requirements() -> None:
    rules = (_rule("cache.zone-redundant"), _rule("cache.tls"))
    records = _resources(("cache-1", "cache"), ("cache-2", "cache"))
    results = {"cache.tls": PolicyResult(denied=True, context={"deny_reason": "tls"})}
    coverage = await _coverage(rules, records, results=results)

    assert _outcome(coverage, "cache.zone-redundant") == (
        FrameworkSatisfactionStatus.SATISFIED,
        None,
    )
    assert _outcome(coverage, "cache.tls") == (FrameworkSatisfactionStatus.FAILED, None)
    replayed = await _coverage(rules, records, results=results)
    assert replayed.coverage_digest == coverage.coverage_digest


@pytest.mark.asyncio
async def test_outcome_table_precedence_is_fail_closed() -> None:
    rules = (_rule("cache.zone-redundant"),)
    coverage = await _coverage(
        rules,
        _resources(("cache-1", "cache")),
        requested=("cache.not-activated",),
    )
    other_scope = canonical_digest({"workload_id": "other"})
    drifted_pin = replace(coverage.activation, rule_catalog_digest="sha256:" + "f" * 64)
    stale = NOW + timedelta(days=2)

    assert _outcome(coverage, "cache.zone-redundant", scope_digest=other_scope) == (
        UNKNOWN,
        RuleEvidenceLimitation.SCOPE_MISMATCH,
    )
    assert _outcome(coverage, "cache.not-activated") == (
        UNKNOWN,
        RuleEvidenceLimitation.RULE_NOT_ACTIVATED,
    )
    assert _outcome(coverage, "cache.zone-redundant", pin=drifted_pin) == (
        UNKNOWN,
        RuleEvidenceLimitation.ACTIVATION_CATALOG_DRIFT,
    )
    assert _outcome(coverage, "cache.zone-redundant", evaluated_at=stale) == (
        UNKNOWN,
        RuleEvidenceLimitation.STALE_INVENTORY,
    )
    # An earlier row wins over every later row.
    assert _outcome(
        coverage,
        "cache.zone-redundant",
        scope_digest=other_scope,
        evaluated_at=stale,
    ) == (UNKNOWN, RuleEvidenceLimitation.SCOPE_MISMATCH)


@pytest.mark.asyncio
async def test_revision_drift_between_activation_and_evaluated_rule_stays_unknown() -> None:
    evaluated = _rule("cache.zone-redundant")
    activated = evaluated.model_copy(update={"version": "1.0.1"})
    coverage = await _coverage(
        (evaluated,),
        _resources(("cache-1", "cache")),
        activation=_activation(activated),
    )

    assert _outcome(coverage, "cache.zone-redundant") == (
        UNKNOWN,
        RuleEvidenceLimitation.RULE_REVISION_DRIFT,
    )


@pytest.mark.asyncio
async def test_missing_duplicate_conflicting_and_unexpected_pairs_stay_unknown() -> None:
    rules = (_rule("cache.zone-redundant"),)
    records = _resources(("cache-1", "cache"), ("cache-2", "cache"))
    outcomes = await _baseline(rules, records)
    first = next(item for item in outcomes if item.resource_ref == "resource:cache-1")
    second = next(item for item in outcomes if item.resource_ref == "resource:cache-2")
    violated = await _baseline(
        rules,
        records,
        {"cache.zone-redundant": PolicyResult(denied=True, context={"deny_reason": "zone"})},
    )
    first_violated = next(item for item in violated if item.resource_ref == "resource:cache-1")

    cases = {
        RuleEvidenceLimitation.PAIR_MISSING: (first,),
        RuleEvidenceLimitation.DUPLICATE_PAIR: (first, first, second),
        RuleEvidenceLimitation.CONFLICTING_PAIR: (first, first_violated, second),
    }
    for limitation, selected in cases.items():
        coverage = await _coverage(rules, records, outcomes=selected)
        assert _outcome(coverage, "cache.zone-redundant") == (UNKNOWN, limitation)

    # cache-2 stays in the workload, but its type no longer dispatches the Rule.
    retyped = _resources(("cache-1", "cache"), ("cache-2", "queue"))
    coverage = await _coverage(rules, records, workload=retyped, outcomes=outcomes)
    assert _outcome(coverage, "cache.zone-redundant") == (
        UNKNOWN,
        RuleEvidenceLimitation.UNEXPECTED_PAIR,
    )


@pytest.mark.asyncio
async def test_no_eligible_resource_and_held_for_review_stay_unknown() -> None:
    rules = (_rule("cache.zone-redundant"), _rule("sql.backup", resource_type="sql-database"))
    coverage = await _coverage(
        rules,
        _resources(("cache-1", "cache")),
        results={"cache.zone-redundant": None},
    )

    assert _outcome(coverage, "sql.backup") == (
        UNKNOWN,
        RuleEvidenceLimitation.NO_ELIGIBLE_RESOURCE,
    )
    assert _outcome(coverage, "cache.zone-redundant") == (
        UNKNOWN,
        RuleEvidenceLimitation.HELD_FOR_REVIEW,
    )


@pytest.mark.asyncio
async def test_workload_projection_ignores_out_of_scope_outcomes() -> None:
    rules = (_rule("cache.zone-redundant"),)
    coverage = await _coverage(
        rules,
        _resources(("cache-1", "cache"), ("cache-outside", "cache")),
        workload=_resources(("cache-1", "cache")),
        results={"cache.zone-redundant": PolicyResult(denied=False, context={})},
    )

    assert _outcome(coverage, "cache.zone-redundant") == (
        FrameworkSatisfactionStatus.SATISFIED,
        None,
    )


@pytest.mark.asyncio
async def test_coverage_rejects_foreign_generations_and_non_member_pairs() -> None:
    rules = (_rule("cache.zone-redundant"),)
    records = _resources(("cache-1", "cache"))
    outcomes = await _baseline(rules, records)
    foreign = outcomes[0].model_copy(update={"generation_id": "generation:other"})

    with pytest.raises(ValueError, match="pinned inventory generation"):
        await _coverage(rules, records, outcomes=(foreign,))
    with pytest.raises(ValueError, match="activation members"):
        await _coverage(rules, records, activation=_activation(_rule("cache.other")))
    with pytest.raises(ValueError, match="unique resource ids"):
        expected_rule_pairs(resources=_workload(records + records), index=RuleIndex.build(rules))


def _waf() -> FrameworkAssessmentCatalog:
    return load_framework_assessment_catalog(
        ROOT / "rule-catalog/framework-assessments/generated/azure-waf.json"
    )


def _waf_rule_ids(catalog: FrameworkAssessmentCatalog) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                requirement.source_ref
                for control in catalog.controls
                for requirement in control.evidence
                if requirement.kind is FrameworkRequirementKind.RULE
            }
        )
    )


def _assess(
    catalog: FrameworkAssessmentCatalog,
    receipts: tuple[FrameworkEvidenceReceipt, ...],
    pin: FrameworkRuleActivationPin | None,
) -> FrameworkAssessmentResult:
    profile = FrameworkAssessmentProfile.create(
        profile_id="azure-waf-profile",
        framework_id=catalog.framework_id,
        framework_version=catalog.framework_version,
        catalog_digest=catalog.catalog_digest,
        scope_kind=FrameworkScopeKind.WORKLOAD,
        scope_digest=SCOPE_DIGEST,
        ontology_release="2026.10",
        applicability=tuple(
            FrameworkApplicabilityDecision(
                control_id=control.control_id,
                status=FrameworkApplicabilityStatus.APPLICABLE,
                requested_by="requester@example.com",
                owner_slot=control.owner_slot,
                cadence_days=control.cadence_days,
            )
            for control in catalog.controls
        ),
        owners=tuple(
            FrameworkOwnerBinding(
                control_id=control.control_id,
                owner_slot=control.owner_slot,
                owner_identity=f"{control.owner_slot}@example.com",
            )
            for control in catalog.controls
        ),
        reviewed_by="reviewer@example.com",
        reviewed_at=NOW - timedelta(days=1),
        inventory_generation=GENERATION,
        rule_activation=pin,
    )
    return FrameworkAssessmentRuntime(catalog).assess(
        FrameworkAssessmentRequest(
            assessment_id="assessment-waf",
            profile=profile,
            evaluated_at=NOW,
            recorded_at=NOW,
            evidence=receipts,
        )
    )


def _rule_limitations(result: FrameworkAssessmentResult) -> set[str]:
    return {
        limitation
        for control in result.controls
        for requirement in control.requirements
        if requirement.requirement_id.startswith("rule:")
        for limitation in requirement.limitations
    }


async def _waf_receipts(
    catalog: FrameworkAssessmentCatalog,
    activated: tuple[Rule, ...],
) -> tuple[tuple[FrameworkEvidenceReceipt, ...], FrameworkRuleActivationPin]:
    activation = _activation(*activated)
    coverage = await _coverage(activated, _resources(("cache-1", "cache")), activation=activation)
    pin = activation_pin(activation)
    receipts = build_rule_requirement_receipts(
        catalog=catalog,
        coverage=coverage,
        profile_scope_digest=SCOPE_DIGEST,
        pinned_activation=pin,
        evaluated_at=NOW,
        source_identity="forseti",
    )
    return receipts, pin


@pytest.mark.asyncio
async def test_waf_rule_receipts_are_admitted_only_with_the_assessment_activation_pin() -> None:
    catalog = _waf()
    rules = tuple(_rule(rule_id) for rule_id in _waf_rule_ids(catalog))
    receipts, pin = await _waf_receipts(catalog, rules)

    assert len(receipts) == 36
    assert len({item.control_id for item in receipts}) == 8
    assert all(item.outcome is FrameworkSatisfactionStatus.SATISFIED for item in receipts)

    assert "rule_activation_unpinned" in _rule_limitations(_assess(catalog, receipts, None))
    other = replace(pin, generation_digest="sha256:" + "e" * 64)
    assert "rule_activation_mismatch" in _rule_limitations(_assess(catalog, receipts, other))
    pinned = _rule_limitations(_assess(catalog, receipts, pin))
    assert not {"rule_activation_unpinned", "rule_activation_mismatch"} & pinned
    assert "decisive_evidence_unavailable" not in pinned

    unprovenanced = tuple(replace(item, rule_provenance=None) for item in receipts)
    assert "rule_provenance_missing" in _rule_limitations(_assess(catalog, unprovenanced, pin))


@pytest.mark.asyncio
async def test_unknown_receipts_surface_limitation_codes_in_the_assessment() -> None:
    catalog = _waf()
    receipts, pin = await _waf_receipts(catalog, (_rule("cache.zone-redundant"),))
    not_activated = [item for item in receipts if item.limitations == ("rule_not_activated",)]

    assert not_activated
    assert all(item.outcome is UNKNOWN for item in not_activated)
    result = _assess(catalog, receipts, pin)
    assert "rule_not_activated" in _rule_limitations(result)
    assert result.execution_authority is False


def test_receipt_and_profile_reject_invalid_rule_fields() -> None:
    catalog = _waf()
    with pytest.raises(ValueError, match="generation_id"):
        FrameworkRuleActivationPin(
            generation_id="not-a-generation",
            generation_digest="sha256:" + "a" * 64,
            rule_catalog_digest="sha256:" + "b" * 64,
        )
    pin = FrameworkRuleActivationPin(
        generation_id="rule-activation-" + "a" * 32,
        generation_digest="sha256:" + "a" * 64,
        rule_catalog_digest="sha256:" + "b" * 64,
    )
    result = _assess(catalog, (), pin)
    assert result.profile_digest != _assess(catalog, (), None).profile_digest


@pytest.mark.asyncio
async def test_unattributed_outcomes_and_invalid_inputs_fail_closed() -> None:
    member = _rule("cache.zone-redundant")
    stranger = _rule("cache.unlisted")
    records = _resources(("cache-1", "cache"))
    outcomes = await _baseline((member, stranger), records)
    workload = _workload(records)
    expected = expected_rule_pairs(resources=workload, index=RuleIndex.build((member,)))
    values: dict[str, Any] = {
        "scope_digest": SCOPE_DIGEST,
        "resources": workload,
        "expected_pairs": expected,
        "outcomes": outcomes,
        "activation": _activation(member),
        "requested_rule_ids": (),
        "inventory_generation": GENERATION,
        "inventory_observed_at": NOW - timedelta(minutes=5),
        "recorded_at": NOW - timedelta(minutes=4),
    }

    coverage = build_scoped_coverage(**values)
    assert coverage.unattributed_unexpected_count == 1
    assert _outcome(coverage, "cache.zone-redundant") == (
        UNKNOWN,
        RuleEvidenceLimitation.UNEXPECTED_PAIR,
    )

    invalid: list[tuple[dict[str, Any], str]] = [
        ({"scope_digest": "workload-1"}, "scope_digest"),
        ({"recorded_at": (NOW - timedelta(minutes=4)).replace(tzinfo=None)}, "timezone-aware"),
        ({"recorded_at": NOW - timedelta(minutes=6)}, "follow the observation"),
        ({"resources": ()}, "inside the workload scope"),
    ]
    for change, message in invalid:
        with pytest.raises(ValueError, match=message):
            build_scoped_coverage(**{**values, **change})
    with pytest.raises(ValueError, match="id and a type"):
        WorkloadRuleResource(resource_id=" ", resource_type="cache")
    assert canonical_sha256("a" * 64) == "sha256:" + "a" * 64
