"""Tests for simulated business ontology, 52-rule objective bindings, K6-K8, and Q&A."""

from __future__ import annotations

from pathlib import Path

import yaml
from fdai.core.assurance_twin.state_trajectory import InvariantStatus, TrajectoryOutcomeStatus
from fdai.core.ontology_platform.simulated_business_ontology import (
    answer_business_concept_query,
    build_simulated_business_operating_model,
    project_all_authored_rule_objectives,
    run_simulated_business_ontology_suite,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Autonomy, CheckLogicKind
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[5]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"


def _load_catalog_and_rules():
    schema_registry = PackageResourceSchemaRegistry()
    catalog = load_ontology_catalog(
        CATALOG_ROOT,
        schema_registry=schema_registry,
        probes_root=CATALOG_ROOT / "probes",
    )
    action_types = load_action_type_catalog(
        CATALOG_ROOT / "action-types",
        schema_registry=schema_registry,
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load((CATALOG_ROOT / "vocabulary" / "resource-types.yaml").read_text("utf-8"))
    )
    rules = load_rule_catalog(
        CATALOG_ROOT / "catalog",
        schema_registry=schema_registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=CATALOG_ROOT / "remediation",
    )
    authored = tuple(rule for rule in rules if rule.check_logic.kind is CheckLogicKind.REGO)
    return catalog, authored


async def test_simulated_business_ontology_suite_closes_scope_rules_k6_k8_and_qa() -> None:
    catalog, authored_rules = _load_catalog_and_rules()
    assert len(authored_rules) == 52

    result = await run_simulated_business_ontology_suite(
        catalog=catalog,
        rules=authored_rules,
        repo_root=REPO_ROOT,
    )

    # 1. Business Operating Scope: 100% mapped resources (0 unknown_service)
    assert result.scope_coverage.complete is True
    assert result.scope_coverage.unmapped_resource_ids == ()
    assert len(result.scope_coverage.resources) == 6
    assert all(item.mapped and not item.conflicting for item in result.scope_coverage.resources)

    # 2. OperationalContextSnapshot: 6/6 resources ENFORCE_AUTO with 0 conflicts/stale sources
    assert len(result.context_snapshots) == 6
    for ctx in result.context_snapshots:
        assert ctx.autonomy_ceiling is Autonomy.ENFORCE_AUTO
        assert ctx.conflicts == ()
        assert ctx.stale_sources == ()
        assert len(ctx.service_ids) == 1
        assert len(ctx.workload_ids) >= 1
        assert len(ctx.service_objective_ids) == 1
        assert len(ctx.recovery_objective_ids) == 1
        assert len(ctx.cost_objective_ids) == 1
        assert len(ctx.constraint_ids) == 1
        assert len(ctx.ownership_ids) == 1

    # 3. 52/52 Authored Rules bound to ControlObjectives with EquivalenceValidationReceipts
    assert len(result.rule_migration_report.authored_rule_refs) == 52
    assert len(result.rule_migration_report.bound_rule_refs) == 52
    assert (
        result.rule_migration_report.bound_rule_refs
        == result.rule_migration_report.authored_rule_refs
    )
    assert result.rule_migration_report.ambiguous_rule_refs == ()
    assert len(result.rule_binding_projection.objects) == 104  # 52 bindings + 52 receipts
    assert len(result.rule_binding_projection.links) == 156  # 52 * 3 links

    # 4. K6-K8 Graph-Wide Dynamic Trajectory Simulation & Independent Closure
    assert result.dynamic_simulation.requires_review is False
    assert result.dynamic_simulation.reason_codes == ()
    assert len(result.dynamic_simulation.invariant_results) == 1
    assert result.dynamic_simulation.invariant_results[0].status is InvariantStatus.PASSED
    assert result.trajectory_closure.closed is True
    assert result.trajectory_closure.outcome.status is TrajectoryOutcomeStatus.MATCHED

    # 5. Business-Concept Q&A (by Korean alias, English alias, and canonical ID)
    for query in ("결제 서비스", "checkout-service", "svc-checkout-api"):
        answer = await answer_business_concept_query(result.store, query_term=query)
        assert answer is not None
        assert answer.service_id == "svc-checkout-api"
        assert answer.criticality == "tier-1-critical"
        assert answer.capability_ids == ("cap-commerce-checkout",)
        assert answer.workload_ids == ("wl-checkout-aks",)
        assert answer.resource_ids == ("res-aks-checkout-01", "res-kv-secrets-01")
        assert answer.service_objective_ids == ("obj-slo-checkout",)
        assert answer.recovery_objective_ids == ("obj-rto-checkout",)
        assert answer.cost_objective_ids == ("obj-cost-checkout",)
        assert answer.budget_ids == ("budget-checkout",)
        assert answer.constraint_ids == ("constraint-checkout-ha",)
        assert answer.ownership_ids == ("owner-checkout",)

    orders_answer = await answer_business_concept_query(result.store, query_term="주문 처리 서비스")
    assert orders_answer is not None
    assert orders_answer.service_id == "svc-order-processor"
    assert orders_answer.budget_ids == ("budget-orders",)

    rec_answer = await answer_business_concept_query(result.store, query_term="추천 엔진 서비스")
    assert rec_answer is not None
    assert rec_answer.service_id == "svc-recommendation-engine"
    assert rec_answer.cost_objective_ids == ("obj-cost-rec",)
    assert await answer_business_concept_query(result.store, query_term="nonexistent") is None
    assert len(build_simulated_business_operating_model().objects) == 36
    projected_rules, _ = project_all_authored_rule_objectives(
        rules=authored_rules, repo_root=REPO_ROOT
    )
    assert len(projected_rules.objects) == 104
