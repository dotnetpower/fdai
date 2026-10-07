"""Workload projection of Forseti's version 2 baseline into framework Rule receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai.agents import (
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    ForsetiBaselineWorker,
)
from fdai.core.framework_assessment import (
    FrameworkAssessmentRuntime,
    FrameworkAssessmentService,
    FrameworkSatisfactionStatus,
)
from fdai.core.rule_activation.generation import build_rule_activation_generation
from fdai.core.tiers.t0_deterministic import (
    PolicyResult,
    RuleGenerationSnapshot,
    RuleIndex,
    T0Engine,
)
from fdai.delivery.framework_assessment_cli import (
    FrameworkAssessmentJobSettings,
    _waf_scope_digest,
    execute_framework_assessment_tick,
)
from fdai.delivery.framework_rule_evidence_source import (
    WorkloadRuleEvidenceStatus,
    load_workload_rule_evidence,
)
from fdai.delivery.persistence.postgres_wara_scope import (
    WaraResolvedResource,
    WaraResolvedScope,
)
from fdai.rule_catalog.schema.framework_assessment import load_framework_assessment_catalog
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
from fdai.shared.providers.inventory import PromotedInventoryGeneration, ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation import RuleActivationGeneration

ROOT = Path(__file__).resolve().parents[4]
WAF = load_framework_assessment_catalog(
    ROOT / "rule-catalog/framework-assessments/generated/azure-waf.json"
)
NOW = datetime(2026, 10, 2, tzinfo=UTC)
VIOLATED_RULE = "kubernetes-cluster.diagnostic-settings-required"
COMPLIANT_RULE = "object-storage.diagnostic-settings-required"


class _Store(InMemoryStateStore):
    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        del entry


class _Evaluator:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del resource_props
        return PolicyResult(denied=rule.id == VIOLATED_RULE, context={})


class _Reader:
    def __init__(self, generation: PromotedInventoryGeneration) -> None:
        self.generation = generation

    async def active_generation_id(self) -> str:
        return self.generation.generation

    async def load_active_generation(self, *, max_resources: int) -> PromotedInventoryGeneration:
        del max_resources
        return self.generation


def _rule(rule_id: str, resource_type: str) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediation/example.tftpl"),
        remediates="remediate.example",
        triggered_by=["inventory.resource_observed"],
        provenance=Provenance(
            source_url="https://example.com/rule",
            resolved_ref="0" * 40,
            content_hash="sha256:example",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=NOW,
        ),
    )


RULES = (_rule(VIOLATED_RULE, "kubernetes"), _rule(COMPLIANT_RULE, "storage"))


def _activation() -> RuleActivationGeneration:
    return build_rule_activation_generation(
        RULES, profile_id="waf-test", profile_version="1.0.0", created_at=NOW
    )


def _scope(*, generation: str = "inventory-1") -> WaraResolvedScope:
    return WaraResolvedScope(
        workload_id="workload-example",
        ontology_release="2026.09",
        inventory_generation=generation,
        resources=(
            WaraResolvedResource(
                neutral_resource_id="cluster-1",
                provider_resource_id="/providers/example/cluster-1",
                provider_resource_type="Example/clusters",
            ),
            WaraResolvedResource(
                neutral_resource_id="storage-1",
                provider_resource_id="/providers/example/storage-1",
                provider_resource_type="Example/storage",
            ),
        ),
    )


async def _baseline(store: InMemoryStateStore, activation: RuleActivationGeneration) -> None:
    generation = PromotedInventoryGeneration(
        generation="inventory-1",
        resources=(
            ResourceRecord(resource_id="cluster-1", type="kubernetes", props={}),
            ResourceRecord(resource_id="outside-1", type="kubernetes", props={}),
            ResourceRecord(resource_id="storage-1", type="storage", props={}),
        ),
        complete=True,
        recorded_at=NOW,
    )
    engine = T0Engine(index=RuleIndex.build(RULES), evaluator=_Evaluator())

    async def activation_source() -> RuleActivationGeneration:
        return activation

    async def snapshot_source() -> RuleGenerationSnapshot:
        return RuleGenerationSnapshot(
            engine=engine, rules=RULES, generation_digest=activation.generation_digest
        )

    await ForsetiBaselineWorker(
        state_store=store,
        reader=_Reader(generation),
        activation_source=activation_source,
        rule_snapshot_source=snapshot_source,
        owner="forseti-test",
        clock=lambda: NOW,
    ).run_once()


async def _load(
    store: InMemoryStateStore,
    activation: RuleActivationGeneration | None,
    *,
    scope: WaraResolvedScope | None = None,
):
    resolved = scope or _scope()
    return await load_workload_rule_evidence(
        state_store=store,
        activation=activation,
        scope=resolved,
        catalog=WAF,
        profile_scope_digest=_waf_scope_digest(resolved),
        evaluated_at=NOW,
        source_identity="forseti-baseline-evaluation",
    )


@pytest.mark.asyncio
async def test_complete_baseline_yields_one_receipt_per_rule_requirement() -> None:
    store = _Store()
    activation = _activation()
    await _baseline(store, activation)

    evidence = await _load(store, activation)

    assert evidence.status is WorkloadRuleEvidenceStatus.READY
    assert evidence.pin is not None
    rule_requirements = [
        requirement
        for control in WAF.controls
        for requirement in control.evidence
        if requirement.kind.value == "rule"
    ]
    assert len(evidence.receipts) == len(rule_requirements)
    by_rule = {item.requirement_id.removeprefix("rule:"): item for item in evidence.receipts}
    assert by_rule[VIOLATED_RULE].outcome is FrameworkSatisfactionStatus.FAILED
    assert by_rule[COMPLIANT_RULE].outcome is FrameworkSatisfactionStatus.SATISFIED
    others = [item for key, item in by_rule.items() if key not in {VIOLATED_RULE, COMPLIANT_RULE}]
    assert all(item.outcome is FrameworkSatisfactionStatus.UNKNOWN for item in others)
    assert all(item.limitations == ("rule_not_activated",) for item in others)


@pytest.mark.asyncio
async def test_tick_pins_activation_and_admits_rule_receipts(tmp_path: Path) -> None:
    store = _Store()
    activation = _activation()
    await _baseline(store, activation)
    evidence = await _load(store, activation)
    hierarchy = tmp_path / "hierarchy.json"
    hierarchy.write_text(
        json.dumps(
            {
                "count": 1,
                "totalRecords": 1,
                "resultTruncated": False,
                "data": [{"name": "root"}],
            }
        )
    )
    audit: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    class AuditStore:
        async def append_audit_entry(self, entry: Mapping[str, object]) -> None:
            audit.append(dict(entry))

    class Bus:
        async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
            del topic, key
            events.append(dict(payload))
            return object()

    caf = load_framework_assessment_catalog(
        ROOT / "rule-catalog/framework-assessments/generated/azure-caf.json"
    )
    report = await execute_framework_assessment_tick(
        settings=FrameworkAssessmentJobSettings(
            dsn="postgresql://localhost/example",
            workload_id="workload-example",
            inventory_freshness_seconds=86_400,
            maximum_resources=1_000,
            tenant_id="tenant-example",
            subscription_id="subscription-example",
            hierarchy_path=hierarchy,
            reviewer_identity="reviewer@example.com",
        ),
        scope=_scope(),
        waf_service=FrameworkAssessmentService(
            FrameworkAssessmentRuntime(WAF), AuditStore(), Bus()
        ),
        caf_service=FrameworkAssessmentService(
            FrameworkAssessmentRuntime(caf), AuditStore(), Bus()
        ),
        waf_catalog=WAF,
        caf_catalog=caf,
        now=NOW,
        source_revision="a" * 40,
        rule_evidence=evidence,
    )

    assert report.rule_evidence_status == "ready"
    assert report.rule_receipt_count == len(evidence.receipts)
    assert report.to_dict()["execution_authority"] is False
    assert report.waf_counts["satisfaction.failed"] >= 1
    assert report.waf_counts["evaluation.evaluated"] >= 1
    assert "rule_activation_mismatch" not in json.dumps(events)


@pytest.mark.asyncio
async def test_missing_activation_or_baseline_yields_no_receipts() -> None:
    store = _Store()

    assert (await _load(store, None)).status is WorkloadRuleEvidenceStatus.NO_ACTIVATION
    missing = await _load(store, _activation())
    assert missing.status is WorkloadRuleEvidenceStatus.NO_BASELINE
    assert missing.pin is not None and missing.receipts == ()


@pytest.mark.asyncio
async def test_baseline_for_other_activation_or_generation_is_not_used() -> None:
    store = _Store()
    await _baseline(store, _activation())
    other = build_rule_activation_generation(
        RULES[:1], profile_id="waf-test", profile_version="1.0.0", created_at=NOW
    )

    drift = await _load(store, other)
    mismatch = await _load(store, _activation(), scope=_scope(generation="inventory-2"))

    assert drift.status is WorkloadRuleEvidenceStatus.BASELINE_ACTIVATION_DRIFT
    assert mismatch.status is WorkloadRuleEvidenceStatus.BASELINE_GENERATION_MISMATCH
    assert drift.receipts == mismatch.receipts == ()


@pytest.mark.asyncio
async def test_removed_outcome_fails_outcome_set_verification() -> None:
    store = _Store()
    activation = _activation()
    await _baseline(store, activation)
    rows, _ = await store.read_state_page(BASELINE_EVALUATION_OUTCOME_PREFIX, limit=100)
    victim = next(row for row in rows if "cluster-1" in str(row["resource_ref"]))
    keys = [
        key
        for key, value in store._state.items()  # noqa: SLF001 - simulate a lost record
        if key.startswith(BASELINE_EVALUATION_OUTCOME_PREFIX) and value == victim
    ]
    for key in keys:
        del store._state[key]  # noqa: SLF001

    evidence = await _load(store, activation)

    assert evidence.status is WorkloadRuleEvidenceStatus.BASELINE_OUTCOMES_UNVERIFIED
    assert evidence.receipts == ()


@pytest.mark.asyncio
async def test_same_rules_under_a_new_activation_profile_stay_verifiable() -> None:
    store = _Store()
    first = _activation()
    second = build_rule_activation_generation(
        RULES, profile_id="waf-test", profile_version="2.0.0", created_at=NOW
    )
    await _baseline(store, first)

    later = datetime(2026, 10, 3, tzinfo=UTC)
    generation = PromotedInventoryGeneration(
        generation="inventory-1",
        resources=(
            ResourceRecord(resource_id="cluster-1", type="kubernetes", props={}),
            ResourceRecord(resource_id="outside-1", type="kubernetes", props={}),
            ResourceRecord(resource_id="storage-1", type="storage", props={}),
        ),
        complete=True,
        recorded_at=NOW,
    )
    engine = T0Engine(index=RuleIndex.build(RULES), evaluator=_Evaluator())

    async def activation_source() -> RuleActivationGeneration:
        return second

    async def snapshot_source() -> RuleGenerationSnapshot:
        return RuleGenerationSnapshot(
            engine=engine, rules=RULES, generation_digest=second.generation_digest
        )

    await ForsetiBaselineWorker(
        state_store=store,
        reader=_Reader(generation),
        activation_source=activation_source,
        rule_snapshot_source=snapshot_source,
        owner="forseti-test",
        clock=lambda: later,
    ).run_once()

    evidence = await _load(store, second)

    assert evidence.status is WorkloadRuleEvidenceStatus.READY
