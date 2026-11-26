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


async def test_business_ontology_extensions_interfaces_bilingual_terms_and_clarification() -> None:
    from decimal import Decimal

    from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
    from fdai.core.ontology_platform.business_ontology_extensions import (
        BILINGUAL_OBJECT_QUERY_TERMS,
        build_expanded_interface_catalog,
        enrich_object_types_with_bilingual_query_terms,
        evaluate_service_budget_burn,
        extended_business_function_types,
        extended_business_link_types,
        extended_business_object_types,
        resolve_business_service_or_clarify,
    )
    from fdai.shared.ontology.release import build_ontology_release

    catalog, authored_rules = _load_catalog_and_rules()
    base_release = catalog.build_release()
    enriched_objects = enrich_object_types_with_bilingual_query_terms(catalog.object_types)
    assert len(enriched_objects) == 89
    assert all(len(obj.query_terms) >= 2 for obj in enriched_objects)
    # Enriching query_terms preserves the exact canonical OntologyRelease digest
    enriched_release = build_ontology_release(
        object_types=enriched_objects,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=catalog.function_types,
    )
    assert enriched_release.digest == base_release.digest

    ext_objs = extended_business_object_types()
    ext_links = extended_business_link_types()
    ext_fns = extended_business_function_types()
    assert {o.name for o in ext_objs} == {"CostAllocation", "ExternalSlaContract"}
    assert len(ext_links) == 3
    assert len(ext_fns) == 4
    assert len(BILINGUAL_OBJECT_QUERY_TERMS) == 91

    compiled_ifaces = build_expanded_interface_catalog(catalog)
    assert len(compiled_ifaces.resolve("Identifiable")) == 91
    assert compiled_ifaces.resolve("Ownable") == (
        "BusinessService",
        "Resource",
        "ServiceObjective",
        "Workload",
    )
    assert "CostAllocation" in compiled_ifaces.resolve("CostBearing")
    assert "ExternalSlaContract" in compiled_ifaces.resolve("ObjectiveBound")

    assert SemanticOutputShape.BUSINESS_SERVICE_OBJECTIVE_POSTURE.value == (
        "business_service_objective_posture"
    )
    assert SemanticOutputShape.BUSINESS_SERVICE_BUDGET_BURN.value == "business_service_budget_burn"
    assert SemanticOutputShape.DECISION_EXPECTED_VS_OBSERVED_OUTCOME.value == (
        "decision_expected_vs_observed_outcome"
    )

    suite = await run_simulated_business_ontology_suite(
        catalog=catalog,
        rules=authored_rules,
        repo_root=REPO_ROOT,
    )
    exact = await resolve_business_service_or_clarify(suite.store, utterance_target="결제 서비스")
    assert exact.requires_clarification is False
    assert exact.resolved_service_id == "svc-checkout-api"

    ambiguous = await resolve_business_service_or_clarify(
        suite.store, utterance_target="알 수 없는 서비스"
    )
    assert ambiguous.requires_clarification is True
    assert len(ambiguous.candidate_services) == 3
    assert ambiguous.clarification_prompt is not None
    assert "svc-checkout-api" in ambiguous.clarification_prompt

    burn = evaluate_service_budget_burn(
        service_id="svc-checkout-api",
        budget_id="budget-checkout",
        budget_limit=Decimal("15000.00"),
        direct_spend=Decimal("9500.00"),
        allocated_shared_spend=Decimal("2500.00"),
    )
    assert burn.total_spend == Decimal("12000.00")
    assert burn.burn_ratio == 0.8
    assert burn.status == "within_budget"


def test_k6_k8_interaction_attribution_conflict_readback_and_scenario_what_if() -> None:
    from fdai.core.ontology_platform import (
        resolve_cross_source_conflict_with_readback,
        run_scenario_branch_what_if,
        simulate_interaction_and_attribute_failure,
    )
    from fdai.core.ontology_platform.observation_adjudication import (
        CrossSourceReadConfidence,
        CrossSourceStateStatus,
    )
    from fdai.shared.providers.ontology_instance import OntologyObjectRecord

    catalog, _ = _load_catalog_and_rules()
    release_digest = catalog.build_release().digest

    sim, attr = simulate_interaction_and_attribute_failure(ontology_release=release_digest)
    assert sim.requires_review is False
    assert attr.outcome_status is TrajectoryOutcomeStatus.MISMATCHED
    assert attr.diverged_object_ref == "svc-checkout-api"
    assert attr.diverged_metric == "latency_p95_ms"
    assert attr.responsible_model_ref == "model-aks-to-svc-latency@1.0.0:r1"
    assert attr.faulty_link_path == ("runs_on_inverse", "implemented_by_inverse")
    assert attr.absolute_error > 20.0

    readback = resolve_cross_source_conflict_with_readback(
        target_id="res-aks-checkout-01",
        property_name="power_state",
        provider_value="stopped",
        telemetry_value="running",
        readback_source_id="arm-direct-readback",
        readback_value="running",
    )
    assert readback.initial_status is CrossSourceStateStatus.CONFLICTING
    assert readback.resolved_status is CrossSourceStateStatus.AGREED
    assert readback.confidence is CrossSourceReadConfidence.CORROBORATED
    assert readback.resolved_value == "running"

    snap = build_simulated_business_operating_model()
    downsized_aks = OntologyObjectRecord(
        "res-aks-checkout-01",
        "Resource",
        {
            "id": "res-aks-checkout-01",
            "type": "kubernetes-cluster",
            "name": "res-aks-checkout-01",
            "location": "koreacentral",
        },
        revision=1,
    )
    safe_branch = run_scenario_branch_what_if(
        branch_id="what-if-safe-rightsize",
        base_objects=snap.objects,
        base_links=snap.links,
        upsert_objects=(downsized_aks,),
        ontology_release=release_digest,
        simulated_cpu_delta=0.05,
        latency_slo_threshold_ms=150.0,
    )
    assert safe_branch.safe_to_propose is True
    assert safe_branch.violated_invariant_ids == ()

    unsafe_branch = run_scenario_branch_what_if(
        branch_id="what-if-aggressive-downsize",
        base_objects=snap.objects,
        base_links=snap.links,
        upsert_objects=(downsized_aks,),
        ontology_release=release_digest,
        simulated_cpu_delta=0.25,
        latency_slo_threshold_ms=150.0,
    )
    assert unsafe_branch.safe_to_propose is False
    assert unsafe_branch.violated_invariant_ids == ("inv-checkout-latency-slo",)


async def test_yaml_catalog_extensions_runtime_functions_and_planner_wiring() -> None:
    from datetime import UTC, datetime

    from fdai.core.conversation.semantic_logical_service_frame import (
        build_business_service_posture_or_burn_frame,
        build_service_current_health_clarification,
    )
    from fdai.core.conversation.semantic_logical_service_planning import (
        compile_business_service_posture_or_burn_plan,
    )
    from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
    from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
    from fdai.core.conversation.session import Principal, Role
    from fdai.core.ontology_platform import (
        FunctionInvocationContext,
        OntologyFunctionRegistry,
        OntologyQueryPlanVerifier,
    )
    from fdai.core.ontology_platform.business_ontology_extensions import (
        extended_business_object_types,
        load_authored_rule_objective_bindings_manifest,
        load_business_extended_ontology_catalog,
        register_business_ontology_functions,
    )
    from fdai.core.operational_context.projector import OperatingModelProjector
    from fdai.shared.contracts.models import CeilingRole
    from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
    from fdai_service_contracts.semantic_judgment import (
        SemanticJudgmentProposal,
        SemanticTarget,
    )

    ext_catalog = load_business_extended_ontology_catalog(REPO_ROOT / "rule-catalog")
    assert len(ext_catalog.object_types) == 91
    assert len(ext_catalog.link_types) == 130
    assert len(ext_catalog.function_types) == 5
    assert all(len(obj.query_terms) >= 2 for obj in ext_catalog.object_types)
    objects_by_name = {obj.name: obj for obj in ext_catalog.object_types}
    for declaration in extended_business_object_types():
        loaded = objects_by_name[declaration.name]
        assert loaded.authority_class == declaration.authority_class == "pantheon_owned"
        assert loaded.freshness_max_age_seconds == declaration.freshness_max_age_seconds == 600

    manifest_proj, manifest_report = load_authored_rule_objective_bindings_manifest(
        REPO_ROOT / "rule-catalog"
    )
    assert len(manifest_report.bound_rule_refs) == 52
    assert len(manifest_proj.objects) == 104
    assert len(manifest_proj.links) == 156

    release = ext_catalog.build_release()
    store = InMemoryOntologyInstanceStore(
        object_types=ext_catalog.object_types,
        link_types=ext_catalog.link_types,
    )
    projector = OperatingModelProjector(
        store=store,
        object_types=ext_catalog.object_types,
        link_types=ext_catalog.link_types,
    )
    await projector.project(build_simulated_business_operating_model())

    fn_registry = OntologyFunctionRegistry(release=release)
    ext_fns = tuple(
        fn for fn in ext_catalog.function_types if fn.name != "inventory.select_resources"
    )
    register_business_ontology_functions(fn_registry, store=store, declarations=ext_fns)
    ctx = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )
    posture_out, posture_receipt = await fn_registry.invoke_with_receipt(
        "query.business_service_posture",
        {"service_id": "svc-checkout-api"},
        context=ctx,
    )
    assert isinstance(posture_out, dict)
    assert posture_out["authority"] == "none"
    assert posture_receipt.function_ref.name == "query.business_service_posture"

    burn_out, _ = await fn_registry.invoke_with_receipt(
        "query.business_budget_burn",
        {"service_id": "svc-checkout-api"},
        context=ctx,
    )
    assert isinstance(burn_out, dict)
    assert burn_out["status"] == "within_budget"

    # Candidate-suggesting clarification in semantic_logical_service_frame
    ambiguous_judgment = SemanticJudgmentProposal(
        primary_intent="query.ontology_relationships",
        action_posture="advise_only",
        action_subject="none",
        requested_facets=(
            "business_service",
            "workload",
            "resource",
            "current_state",
            "unknown_state",
        ),
        targets=(),
        ambiguous=True,
        unresolved_terms=("BusinessService",),
        clarification="Which BusinessService?",
        confidence=0.9,
    )
    clar = build_service_current_health_clarification(
        ambiguous_judgment,
        utterance="현재 서비스 상태 알려줘",
        context=(),
        candidate_services=("svc-checkout-api", "svc-order-settlement"),
    )
    assert clar is not None
    assert "svc-checkout-api, svc-order-settlement" in (clar[0].clarification or "")

    # Plan compilation for the 3 new SemanticOutputShapes
    provider = CatalogQueryManifestProvider(
        release=release,
        object_types=ext_catalog.object_types,
        link_types=ext_catalog.link_types,
        action_types=ext_catalog.action_types,
        interfaces=ext_catalog.interface_types,
        functions=ext_catalog.function_types,
    )
    q_manifest = provider.manifest_for(
        principal=Principal(id="op-1", role=Role.READER),
        purpose="operations-review",
    )
    from fdai_service_contracts.ontology_query import QueryNodeKind

    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.TYPED_PATH,
            QueryNodeKind.FUNCTION,
            QueryNodeKind.UNION,
        )
    )
    eval_now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    utterance_svc = "Check svc-checkout-api posture and budget"
    svc_start = utterance_svc.index("svc-checkout-api")
    svc_end = svc_start + len("svc-checkout-api")
    for facet_name, expected_shape in (
        ("service_objective_posture", SemanticOutputShape.BUSINESS_SERVICE_OBJECTIVE_POSTURE),
        ("service_budget_burn", SemanticOutputShape.BUSINESS_SERVICE_BUDGET_BURN),
    ):
        j_prop = SemanticJudgmentProposal(
            primary_intent="query.ontology_relationships",
            action_posture="advise_only",
            action_subject="none",
            requested_facets=(facet_name,),
            targets=(
                SemanticTarget(
                    kind="entity_name",
                    value="svc-checkout-api",
                    canonical_value="BusinessService",
                    source_start=svc_start,
                    source_end=svc_end,
                ),
            ),
            ambiguous=False,
            confidence=0.95,
        )
        built = build_business_service_posture_or_burn_frame(
            j_prop,
            utterance=utterance_svc,
            context=(),
        )
        assert built is not None
        assert built[1].output_shape == expected_shape
        compiled = compile_business_service_posture_or_burn_plan(
            frame=built[1],
            utterance=utterance_svc,
            manifest=q_manifest,
            verifier=verifier,
            evaluation_time=eval_now,
            purpose="operations-review",
        )
        assert compiled is not None
        assert compiled.execution_authority is False

    j_dc = SemanticJudgmentProposal(
        primary_intent="query.ontology_relationships",
        action_posture="advise_only",
        action_subject="none",
        requested_facets=("decision_expected_vs_observed_outcome",),
        targets=(),
        ambiguous=False,
        confidence=0.95,
    )
    dc_built = build_business_service_posture_or_burn_frame(
        j_dc,
        utterance="Compare expected vs observed decision outcomes",
        context=(),
    )
    assert dc_built is not None
    assert dc_built[1].output_shape == SemanticOutputShape.DECISION_EXPECTED_VS_OBSERVED_OUTCOME
    dc_plan = compile_business_service_posture_or_burn_plan(
        frame=dc_built[1],
        utterance="Compare expected vs observed decision outcomes",
        manifest=q_manifest,
        verifier=verifier,
        evaluation_time=eval_now,
        purpose="operations-review",
    )
    assert dc_plan is not None
    assert dc_plan.output_node_ids == (
        "decision-cases",
        "decision-expected-effects",
        "decision-observed-outcomes",
    )
