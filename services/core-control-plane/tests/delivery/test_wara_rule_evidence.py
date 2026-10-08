"""WARA recommendations take decisive evidence from a Rule only through a reviewed exact binding."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai.agents import ForsetiBaselineWorker
from fdai.core.rule_activation.generation import build_rule_activation_generation, rule_digest
from fdai.core.tiers.t0_deterministic import (
    PolicyResult,
    RuleGenerationSnapshot,
    RuleIndex,
    T0Engine,
)
from fdai.core.wara import WaraAssessmentRequest, WaraAssessmentRuntime, WaraScopedResource
from fdai.core.wara.runtime import WaraEvaluationStatus, WaraSatisfactionStatus
from fdai.delivery.framework_rule_evidence_source import WorkloadRuleEvidenceStatus
from fdai.delivery.persistence.postgres_wara_scope import WaraResolvedResource, WaraResolvedScope
from fdai.delivery.wara_rule_evidence import (
    _release_rules,
    load_release_wara_rule_bindings,
    with_wara_rule_evidence,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import canonical_digest, load_wara_assessment_catalog
from fdai.rule_catalog.schema.wara_evaluator_binding import load_wara_evaluator_bindings
from fdai.rule_catalog.schema.wara_rule_binding import (
    WaraRuleBindingCatalog,
    load_wara_rule_bindings,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.inventory import PromotedInventoryGeneration, ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation import RuleActivationGeneration

ROOT = Path(__file__).resolve().parents[4]
ASSESSMENT = ROOT / "rule-catalog/collected/wara-aprl/assessment"
NOW = datetime(2026, 10, 8, tzinfo=UTC)
RULE_ID = "secret-store.purge-protection.enabled"
VAULT = "microsoft.keyvault/vaults"


def _catalogs():  # noqa: ANN202
    framework = load_framework_catalog(
        ROOT / "rule-catalog/collected/wara-aprl", best_practices=(), objective_refs=frozenset()
    )[0]
    return load_wara_assessment_catalog(
        ASSESSMENT / "crosswalk.json",
        ASSESSMENT / "queries.json",
        framework=framework,
        framework_path=ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json",
    )


CATALOG, QUERIES = _catalogs()
RELEASE_BINDINGS = load_release_wara_rule_bindings(ROOT, catalog=CATALOG, queries=QUERIES)
# The public APRL identifier lives only in the collected overlay, never as a literal here.
PURGE = next(item.aprl_guid for item in RELEASE_BINDINGS.bindings if item.rule_id == RULE_ID)
EVALUATORS = load_wara_evaluator_bindings(
    ASSESSMENT / "evaluator-bindings.json", catalog=CATALOG, queries=QUERIES
)


class _Store(InMemoryStateStore):
    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        del entry


class _Evaluator:
    def __init__(self, violated: set[str]) -> None:
        self.violated = violated

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        return PolicyResult(denied=resource_props.get("name") in self.violated, context={})


class _Reader:
    def __init__(self, generation: PromotedInventoryGeneration) -> None:
        self.generation = generation

    async def active_generation_id(self) -> str:
        return self.generation.generation

    async def load_active_generation(self, *, max_resources: int) -> PromotedInventoryGeneration:
        del max_resources
        return self.generation


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": RULE_ID,
            "version": "1.0.0",
            "source": "custom",
            "severity": "high",
            "category": "security",
            "resource_type": "secret-store",
            "check_logic": {"kind": "rego", "reference": "policies/example.rego"},
            "remediation": {"template_ref": "remediation/example.tftpl"},
            "remediates": "remediate.example",
            "triggered_by": ["inventory.resource_observed"],
            "evaluates": ["property.secret-store.purge_protection_enabled"],
            "provenance": {
                "source_url": "https://example.com/rule",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": NOW.isoformat(),
            },
        }
    )


def _bound_to(rule: Rule) -> WaraRuleBindingCatalog:
    """The release overlay re-pinned to a fixture Rule body, as a reviewer would re-pin it."""

    material = RELEASE_BINDINGS.model_dump(mode="json")
    material["bindings"][0]["rule_digest"] = "sha256:" + rule_digest(rule)
    material.pop("overlay_digest")
    material["overlay_digest"] = canonical_digest(material)
    return WaraRuleBindingCatalog.model_validate(material)


BINDINGS = _bound_to(_rule())


async def _baseline(store: InMemoryStateStore, *, violated: set[str]) -> RuleActivationGeneration:
    rule = _rule()
    activation = build_rule_activation_generation(
        (rule,), profile_id="wara-test", profile_version="1.0.0", created_at=NOW
    )
    generation = PromotedInventoryGeneration(
        generation="inventory-1",
        resources=tuple(
            ResourceRecord(
                resource_id=name,
                type="secret-store",
                props={"name": name, "purge_protection_enabled": name not in violated},
            )
            for name in ("vault-a", "vault-b")
        ),
        complete=True,
        recorded_at=NOW,
    )
    engine = T0Engine(index=RuleIndex.build((rule,)), evaluator=_Evaluator(violated))

    async def activation_source() -> RuleActivationGeneration:
        return activation

    async def snapshot_source() -> RuleGenerationSnapshot:
        return RuleGenerationSnapshot(
            engine=engine, rules=(rule,), generation_digest=activation.generation_digest
        )

    await ForsetiBaselineWorker(
        state_store=store,
        reader=_Reader(generation),
        activation_source=activation_source,
        rule_snapshot_source=snapshot_source,
        owner="forseti-test",
        clock=lambda: NOW,
    ).run_once()
    return activation


def _scope(*, observed: bool = True) -> WaraResolvedScope:
    return WaraResolvedScope(
        inventory_observed_at=NOW if observed else None,
        workload_id="workload-example",
        ontology_release="2026.10",
        inventory_generation="inventory-1",
        resources=tuple(
            WaraResolvedResource(
                neutral_resource_id=name,
                provider_resource_id=f"/providers/{VAULT}/{name}",
                provider_resource_type=VAULT,
            )
            for name in ("vault-a", "vault-b")
        ),
    )


def _request(scope: WaraResolvedScope) -> WaraAssessmentRequest:
    return WaraAssessmentRequest(
        assessment_id="wara-assessment:test",
        framework_revision=CATALOG.source_revision,
        crosswalk_digest=CATALOG.crosswalk_digest,
        evaluator_bindings_digest=EVALUATORS.overlay_digest,
        ontology_release=scope.ontology_release,
        inventory_generation=scope.inventory_generation,
        workload_id=scope.workload_id,
        resources=tuple(
            WaraScopedResource(
                resource_id=item.provider_resource_id,
                provider_resource_type=item.provider_resource_type,
            )
            for item in scope.resources
        ),
        evaluated_at=NOW,
        recorded_at=NOW,
    )


async def _assess(  # noqa: ANN202
    *,
    violated: set[str],
    activation_override: bool = False,
    bindings: WaraRuleBindingCatalog = BINDINGS,
    observed: bool = True,
):
    store = _Store()
    activation = await _baseline(store, violated=violated)
    if activation_override:
        activation = build_rule_activation_generation(
            (_rule().model_copy(update={"version": "1.0.1"}),),
            profile_id="wara-test",
            profile_version="1.0.0",
            created_at=NOW,
        )
    scope = _scope(observed=observed)
    request, status = await with_wara_rule_evidence(
        _request(scope),
        state_store=store,
        activation=activation,
        scope=scope,
        catalog=CATALOG,
        bindings=bindings,
    )
    result = WaraAssessmentRuntime(CATALOG, EVALUATORS, bindings).assess(request)
    control = next(item for item in result.controls if item.recommendation_id == PURGE)
    return status, request, result, control


def test_release_overlay_binds_only_the_exactly_equivalent_recommendation() -> None:
    bindings = RELEASE_BINDINGS.bindings
    assert [(item.aprl_guid, item.rule_id) for item in bindings] == [(PURGE, RULE_ID)]
    assert bindings[0].capability.failure_semantics == "absent_or_not_true_fails"


@pytest.mark.asyncio
async def test_same_version_with_another_rule_body_yields_no_decisive_receipt() -> None:
    # The release overlay pins the shipped Rule body, which differs from the fixture body.
    _, request, _, control = await _assess(violated=set(), bindings=RELEASE_BINDINGS)

    assert request.evidence == ()
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


@pytest.mark.asyncio
async def test_scope_without_a_snapshot_time_yields_no_rule_receipt() -> None:
    status, request, _, control = await _assess(violated=set(), observed=False)

    assert status is WorkloadRuleEvidenceStatus.BASELINE_INCOMPLETE
    assert request.evidence == ()
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


@pytest.mark.asyncio
async def test_violated_and_compliant_vaults_map_to_failed_and_satisfied() -> None:
    _, request, failed_result, failed = await _assess(violated={"vault-b"})
    _, _, _, satisfied = await _assess(violated=set())

    assert request.rule_bindings_digest == BINDINGS.overlay_digest
    assert (failed.evaluation, failed.satisfaction) == (
        WaraEvaluationStatus.EVALUATED,
        WaraSatisfactionStatus.FAILED,
    )
    assert satisfied.satisfaction is WaraSatisfactionStatus.SATISFIED
    assert failed.evidence_refs[0].startswith("t0-rule-evidence:")
    assert failed_result.to_dict()["rule_bindings_digest"] == BINDINGS.overlay_digest
    others = [item for item in failed_result.controls if item.recommendation_id != PURGE]
    assert all(item.satisfaction is WaraSatisfactionStatus.UNKNOWN for item in others)


@pytest.mark.asyncio
async def test_activation_drift_yields_no_rule_receipt_and_stays_unknown() -> None:
    status, request, _, control = await _assess(violated=set(), activation_override=True)

    assert status is WorkloadRuleEvidenceStatus.BASELINE_ACTIVATION_DRIFT
    assert request.evidence == ()
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


@pytest.mark.asyncio
async def test_query_evidence_is_not_admitted_for_a_rule_bound_recommendation() -> None:
    _, request, _, _ = await _assess(violated=set())
    receipt = request.evidence[0]
    forged = type(receipt)(
        **{
            **{field: getattr(receipt, field) for field in receipt.__dataclass_fields__},
            "evidence_ref": "provider:forged",
            "evidence_kind": "provider_observation",
            "outcome": WaraSatisfactionStatus.SATISFIED,
        }
    )
    result = WaraAssessmentRuntime(CATALOG, EVALUATORS, BINDINGS).assess(
        replace(request, evidence=(forged,))
    )
    control = next(item for item in result.controls if item.recommendation_id == PURGE)
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


def test_runtime_rejects_an_unpinned_or_overlapping_rule_overlay() -> None:
    request = _request(_scope())
    with pytest.raises(ValueError, match="Rule bindings digest mismatch"):
        WaraAssessmentRuntime(CATALOG, EVALUATORS, BINDINGS).assess(request)
    overlapping = EVALUATORS.bindings[0]
    material = BINDINGS.model_dump(mode="json")
    material["bindings"] = [
        {
            **material["bindings"][0],
            "aprl_guid": overlapping.aprl_guid,
            "query_digest": overlapping.query_digest,
        }
    ]
    material.pop("overlay_digest")
    material["overlay_digest"] = canonical_digest(material)
    with pytest.raises(ValueError, match="one evaluator binding kind"):
        WaraAssessmentRuntime(CATALOG, EVALUATORS, WaraRuleBindingCatalog.model_validate(material))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rule_version": "9.9.9"}, "unavailable revision"),
        ({"rule_digest": "sha256:" + "1" * 64}, "unavailable revision"),
        ({"query_digest": "sha256:" + "0" * 64}, "query digest mismatch"),
        ({"capability_fields": ["other_field"]}, "fields differ"),
        ({"capability_type": "object-storage"}, "resource type mismatch"),
    ],
)
def test_loader_rejects_drifted_bindings(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    material = json.loads((ASSESSMENT / "rule-bindings.json").read_text(encoding="utf-8"))
    binding = material["bindings"][0]
    if "capability_fields" in change:
        binding["capability"]["inventory_fields"] = change["capability_fields"]
    elif "capability_type" in change:
        binding["capability"]["canonical_resource_type"] = change["capability_type"]
    else:
        binding.update(change)
    material.pop("overlay_digest")
    material["overlay_digest"] = canonical_digest(material)
    path = tmp_path / "rule-bindings.json"
    path.write_text(json.dumps(material), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_wara_rule_bindings(
            path,
            catalog=CATALOG,
            queries=QUERIES,
            rules=_release_rules(ROOT),
            rule_digest=rule_digest,
        )
