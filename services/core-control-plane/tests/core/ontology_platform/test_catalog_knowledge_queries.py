"""Tests for workflow scenarios, rules, controls, and cloud reference semantic queries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import QueryTable
from fdai.core.ontology_platform.catalog_knowledge_loader import (
    load_catalog_knowledge_corpus,
)
from fdai.core.ontology_platform.catalog_knowledge_queries import (
    CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME,
    CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME,
    CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
    CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
    CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME,
    bind_semantic_catalog_and_decision_functions,
    catalog_knowledge_function_types,
)
from fdai.core.ontology_platform.decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    decision_function_types,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


def _context() -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
    )


async def _invoke_table(
    registry: OntologyFunctionRegistry,
    function_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    raw = await registry.invoke(function_name, arguments, context=_context())
    return cast(dict[str, Any], raw)


def _resource_type() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


async def test_workflow_and_business_scenario_semantic_queries() -> None:
    corpus = load_catalog_knowledge_corpus()
    assert len(corpus.workflows) >= 15
    assert len(corpus.business_scenarios) >= 2

    functions = catalog_knowledge_function_types() + decision_function_types()
    release = build_ontology_release(
        object_types=(_resource_type(),),
        function_types=functions,
    )
    registry = OntologyFunctionRegistry(release=release)
    store = InMemoryOntologyInstanceStore(object_types=(_resource_type(),), link_types=())
    bind_semantic_catalog_and_decision_functions(
        registry=registry,
        declarations={fn.name: fn for fn in functions},
        ontology_release=release,
        ontology_store=store,
        corpus=corpus,
    )

    wf_result = await _invoke_table(
        registry,
        CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME,
        {"query": "blast radius restart", "limit": 5},
    )
    assert wf_result["complete"] is True
    wf_ids = [row["values"]["workflow_id"] for row in wf_result["rows"]]
    assert "blast-radius-gated-service-restart" in wf_ids
    first_wf = next(
        row["values"]
        for row in wf_result["rows"]
        if row["values"]["workflow_id"] == "blast-radius-gated-service-restart"
    )
    assert "ontology-function:decision.blast_radius" in first_wf["gate_refs"]
    assert first_wf["execution_authority"] is False

    scenario_result = await _invoke_table(
        registry,
        CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME,
        {"query": "order fulfillment backlog", "limit": 5},
    )
    scenario_ids = [row["values"]["scenario_id"] for row in scenario_result["rows"]]
    assert "aks-commerce:order-fulfillment" in scenario_ids
    order_scenario = next(
        row["values"]
        for row in scenario_result["rows"]
        if row["values"]["scenario_id"] == "aks-commerce:order-fulfillment"
    )
    assert "decision.blast_radius" in order_scenario["decision_functions"]
    assert "decision.cost_of_delay" in order_scenario["decision_functions"]
    assert any(w["id"] == "order-processor" for w in order_scenario["workloads"])


async def test_rules_controls_wara_mcsb_best_practices_and_governance_chain() -> None:
    corpus = load_catalog_knowledge_corpus()
    functions = catalog_knowledge_function_types()
    release = build_ontology_release(
        object_types=(_resource_type(),),
        function_types=functions,
    )
    registry = OntologyFunctionRegistry(release=release)
    store = InMemoryOntologyInstanceStore(object_types=(_resource_type(),), link_types=())
    bind_semantic_catalog_and_decision_functions(
        registry=registry,
        declarations={fn.name: fn for fn in functions},
        ontology_release=release,
        ontology_store=store,
        corpus=corpus,
    )

    # 1. Atomic rule search (AKS network policy rule)
    rule_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {"query": "kubernetes-cluster.network-policy", "domain": "rule", "limit": 5},
    )
    assert any(r["row_id"] == "rule:kubernetes-cluster.network-policy" for r in rule_res["rows"])
    net_rule = next(
        r["values"]
        for r in rule_res["rows"]
        if r["row_id"] == "rule:kubernetes-cluster.network-policy"
    )
    assert (
        net_rule["metadata"]["remediation_template_ref"]
        == "remediation/kubernetes/enable_network_policy.tftpl"
    )

    # 2. Framework control search (WAF / CAF)
    waf_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {"query": "redundancy RE:05", "domain": "framework_control", "limit": 5},
    )
    assert any("RE:05" in r["row_id"] for r in waf_res["rows"])

    # 3. Korean/English WARA guidance search
    wara_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {"query": "노드 수 user node", "domain": "wara", "limit": 5},
    )
    assert any(r["row_id"] == "wara:005ccbbd" for r in wara_res["rows"])

    # 4. MCSB compliance control + rule/observation crosswalk search
    mcsb_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {"query": "NS-2 network controls", "domain": "mcsb_compliance", "limit": 5},
    )
    ns2 = next(r["values"] for r in mcsb_res["rows"] if r["row_id"] == "mcsb:NS-2")
    assert "object-storage.private-endpoint.required" in ns2["metadata"]["rule_ids"]

    # 5. Best practice search
    bp_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {"query": "financial responsibility CO:01", "domain": "best_practice", "limit": 5},
    )
    assert any("co-01" in r["row_id"] for r in bp_res["rows"])

    # 6. End-to-end governance chain resolution
    chain_res = await _invoke_table(
        registry,
        CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME,
        {"target_id": "kubernetes-cluster.network-policy"},
    )
    chain_vals = chain_res["rows"][0]["values"]
    assert "rule:kubernetes-cluster.network-policy" in chain_vals["matched_rules"]
    assert "aks.network-policies" in chain_vals["matched_cloud_reference_topics"]
    assert "remediate.kubernetes-network-policy" in chain_vals["linked_actions"]
    assert (
        "remediation/kubernetes/enable_network_policy.tftpl" in chain_vals["remediation_templates"]
    )
    assert chain_vals["execution_authority"] is False


async def test_cloud_reference_aks_network_policy_and_unindexed_fallback() -> None:
    corpus = load_catalog_knowledge_corpus()
    functions = catalog_knowledge_function_types()
    release = build_ontology_release(
        object_types=(_resource_type(),),
        function_types=functions,
    )
    registry = OntologyFunctionRegistry(release=release)
    store = InMemoryOntologyInstanceStore(object_types=(_resource_type(),), link_types=())
    bind_semantic_catalog_and_decision_functions(
        registry=registry,
        declarations={fn.name: fn for fn in functions},
        ontology_release=release,
        ontology_store=store,
        corpus=corpus,
    )

    aks_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
        {"query": "AKS 네트워크 정책 종류 calico cilium azure npm", "limit": 5},
    )
    assert aks_res["rows"][0]["row_id"] == "cloud_reference:aks.network-policies"
    topic = aks_res["rows"][0]["values"]
    option_ids = {opt["option_id"] for opt in topic["options"]}
    assert {"azure", "calico", "cilium", "none"} <= option_ids
    cni_modes = {mode["mode_id"] for mode in topic["cni_models"]}
    assert "azure-cni-overlay" in cni_modes
    assert topic["epistemic_status"] == "reviewed_cloud_reference"
    assert topic["execution_authority"] is False

    unindexed_res = await _invoke_table(
        registry,
        CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
        {"query": "quantum photonic hypervisor satellite mesh 9999", "limit": 5},
    )
    assert unindexed_res["rows"][0]["row_id"] == "cloud_reference:unindexed"
    assert unindexed_res["rows"][0]["values"]["limitation_code"] == "cloud_reference_not_indexed"


class _CloudReferencePlanModel:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": [],
            "temporal_scope": {},
            "output_shape": "resource_list",
            "evidence_requirements": [],
            "unresolved_terms": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.95,
        }

    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "aks_ref",
                    "kind": "function",
                    "depends_on": [],
                    "arguments": {
                        "function_name": CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
                        "arguments": {
                            "query": "AKS 네트워크 정책 Calico Cilium",
                            "limit": 5,
                        },
                        "dependency_arguments": {},
                    },
                    "output_kind": "query.table",
                }
            ],
            "output_node_ids": ["aks_ref"],
        }


async def test_semantic_query_runtime_binds_catalog_and_decision_functions() -> None:
    resource = _resource_type()
    functions = operational_function_types(())
    release = build_ontology_release(object_types=(resource,), function_types=functions)
    runtime = build_semantic_query_runtime(
        model=_CloudReferencePlanModel(),
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=(resource,),
            interface_types=(),
            interface_implementations=(),
            link_types=(),
            action_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=InMemoryOntologyInstanceStore(object_types=(resource,), link_types=()),
        now=lambda: datetime(2026, 11, 4, 5, 0, tzinfo=UTC),
    )

    result = await runtime.handle(
        utterance="AKS의 네트워크 정책에는 어떤 것들이 있나요?",
        prior_turns=(),
        principal=Principal(id="reader-1", role=Role.READER),
    )
    assert result.disposition == "answered"
    assert result.execution is not None
    table = result.execution.results["aks_ref"].value
    assert isinstance(table, QueryTable)
    assert table.rows[0].row_id == "cloud_reference:aks.network-policies"
    assert table.rows[0].values["epistemic_status"] == "reviewed_cloud_reference"
    assert BLAST_RADIUS_FUNCTION_NAME in {fn.name for fn in functions}
    assert Path(__file__).exists()
