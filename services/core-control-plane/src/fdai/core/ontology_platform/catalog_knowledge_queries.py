"""Read-only OntologyFunctionTypes for workflows, scenarios, rules, controls, and cloud topics."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai_service_contracts.ontology_query import EvidenceAuthority

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyInstanceStore

from .catalog_knowledge_loader import (
    CatalogKnowledgeCorpus,
    load_catalog_knowledge_corpus,
)
from .functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)

CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME = "catalog.search_workflows"
CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME = "catalog.search_business_scenarios"
CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME = "catalog.search_rules_and_controls"
CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME = "catalog.resolve_governance_chain"
CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME = "catalog.search_cloud_reference"
_PURPOSE = "operations-review"
_MAX_ROWS = 50


def _artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def _query_table_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows", "complete", "truncation_reason"],
        "properties": {
            "rows": {
                "type": "array",
                "maxItems": _MAX_ROWS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["row_id", "values"],
                    "properties": {
                        "row_id": {"type": "string", "minLength": 1, "maxLength": 256},
                        "values": {"type": "object"},
                    },
                },
            },
            "complete": {"type": "boolean"},
            "truncation_reason": {"type": ["string", "null"]},
        },
    }


def _make_query_type(name: str, input_schema: dict[str, Any]) -> OntologyFunctionType:
    return OntologyFunctionType(
        name=name,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_artifact_digest(),
        publisher="fdai",
        input_schema=input_schema,
        output_schema=_query_table_schema(),
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[_PURPOSE],
        timeout_seconds=2,
        cpu_millis=200,
        memory_bytes=67_108_864,
        max_output_bytes=524_288,
        network_allowed=False,
        credentials_allowed=False,
    )


def catalog_search_workflows_function_type() -> OntologyFunctionType:
    return _make_query_type(
        CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 0, "maxLength": 512},
                "gate_ref": {"type": "string", "minLength": 1, "maxLength": 128},
                "action_type_ref": {"type": "string", "minLength": 1, "maxLength": 128},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
    )


def catalog_search_business_scenarios_function_type() -> OntologyFunctionType:
    return _make_query_type(
        CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 0, "maxLength": 512},
                "service_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
    )


def catalog_search_rules_and_controls_function_type() -> OntologyFunctionType:
    return _make_query_type(
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "domain", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 0, "maxLength": 512},
                "domain": {
                    "enum": [
                        "all",
                        "rule",
                        "framework_control",
                        "wara",
                        "best_practice",
                        "mcsb_compliance",
                        "baseline",
                        "probe",
                        "operational_insight",
                        "causal_mechanism",
                    ]
                },
                "resource_type": {"type": "string", "minLength": 1, "maxLength": 128},
                "category": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
    )


def catalog_resolve_governance_chain_function_type() -> OntologyFunctionType:
    return _make_query_type(
        CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["target_id"],
            "properties": {
                "target_id": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        },
    )


def catalog_search_cloud_reference_function_type() -> OntologyFunctionType:
    return _make_query_type(
        CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 0, "maxLength": 512},
                "resource_type": {"type": "string", "minLength": 1, "maxLength": 128},
                "category": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
    )


def catalog_knowledge_function_types() -> tuple[OntologyFunctionType, ...]:
    return (
        catalog_search_workflows_function_type(),
        catalog_search_business_scenarios_function_type(),
        catalog_search_rules_and_controls_function_type(),
        catalog_resolve_governance_chain_function_type(),
        catalog_search_cloud_reference_function_type(),
    )


def _check_context(context: FunctionInvocationContext) -> None:
    if _PURPOSE not in context.purposes:
        raise PermissionError("catalog knowledge query requires operations-review purpose")


def catalog_search_workflows_function(
    ontology_release: OntologyRelease,
    *,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME,
    )
    active_corpus = corpus or load_catalog_knowledge_corpus()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> dict[str, Any]:
        _check_context(invocation_context)
        limit = int(arguments["limit"])
        matches = active_corpus.search_workflows(
            query=str(arguments.get("query", "")),
            gate_ref=arguments.get("gate_ref"),
            action_type_ref=arguments.get("action_type_ref"),
            limit=limit + 1,
        )
        selected = matches[:limit]
        rows = [
            {
                "row_id": f"workflow:{entry.workflow_id}",
                "values": {
                    "ontology_release_digest": ontology_release.digest,
                    "corpus_digest": active_corpus.corpus_digest,
                    "workflow_id": entry.workflow_id,
                    "version": entry.version,
                    "source_scope": entry.source_scope,
                    "description": entry.description,
                    "trigger_kind": entry.trigger_kind,
                    "trigger_signal_or_event": entry.trigger_signal_or_event,
                    "default_mode": entry.default_mode,
                    "gate_refs": list(entry.gate_refs),
                    "action_type_refs": list(entry.action_type_refs),
                    "compensated_by_refs": list(entry.compensated_by_refs),
                    "steps": list(entry.steps),
                    "anti_scope": entry.anti_scope,
                    "content_digest": entry.content_digest,
                    "epistemic_status": "reviewed_catalog_definition",
                    "execution_authority": False,
                },
            }
            for entry in selected
        ]
        complete = len(matches) <= limit
        return {
            "rows": rows,
            "complete": complete,
            "truncation_reason": None if complete else "result_limit",
        }

    return evaluate


def catalog_search_business_scenarios_function(
    ontology_release: OntologyRelease,
    *,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME,
    )
    active_corpus = corpus or load_catalog_knowledge_corpus()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> dict[str, Any]:
        _check_context(invocation_context)
        limit = int(arguments["limit"])
        matches = active_corpus.search_business_scenarios(
            query=str(arguments.get("query", "")),
            service_id=arguments.get("service_id"),
            limit=limit + 1,
        )
        selected = matches[:limit]
        rows = [
            {
                "row_id": f"scenario:{entry.scenario_id}",
                "values": {
                    "ontology_release_digest": ontology_release.digest,
                    "corpus_digest": active_corpus.corpus_digest,
                    "scenario_id": entry.scenario_id,
                    "profile_id": entry.profile_id,
                    "service_id": entry.service_id,
                    "service_name": entry.service_name,
                    "criticality": entry.criticality,
                    "workloads": list(entry.workloads),
                    "dependency_edges": list(entry.dependency_edges),
                    "slo_specs": list(entry.slo_specs),
                    "workflows": list(entry.workflows),
                    "decision_functions": list(entry.decision_functions),
                    "content_digest": entry.content_digest,
                    "epistemic_status": "reviewed_catalog_definition",
                    "execution_authority": False,
                },
            }
            for entry in selected
        ]
        complete = len(matches) <= limit
        return {
            "rows": rows,
            "complete": complete,
            "truncation_reason": None if complete else "result_limit",
        }

    return evaluate


def catalog_search_rules_and_controls_function(
    ontology_release: OntologyRelease,
    *,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
    )
    active_corpus = corpus or load_catalog_knowledge_corpus()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> dict[str, Any]:
        _check_context(invocation_context)
        limit = int(arguments["limit"])
        matches = active_corpus.search_rules_and_controls(
            query=str(arguments.get("query", "")),
            domain=str(arguments.get("domain", "all")),
            resource_type=arguments.get("resource_type"),
            category=arguments.get("category"),
            limit=limit + 1,
        )
        selected = matches[:limit]
        rows = [
            {
                "row_id": record.record_id,
                "values": {
                    "ontology_release_digest": ontology_release.digest,
                    "corpus_digest": active_corpus.corpus_digest,
                    "record_id": record.record_id,
                    "domain": record.domain,
                    "title": record.title,
                    "summary": record.summary,
                    "resource_type": record.resource_type,
                    "category": record.category,
                    "severity": record.severity,
                    "metadata": dict(record.metadata),
                    "content_digest": record.content_digest,
                    "epistemic_status": "reviewed_catalog_definition",
                    "execution_authority": False,
                },
            }
            for record in selected
        ]
        complete = len(matches) <= limit
        return {
            "rows": rows,
            "complete": complete,
            "truncation_reason": None if complete else "result_limit",
        }

    return evaluate


def catalog_resolve_governance_chain_function(
    ontology_release: OntologyRelease,
    *,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME,
    )
    active_corpus = corpus or load_catalog_knowledge_corpus()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> dict[str, Any]:
        _check_context(invocation_context)
        target_id = str(arguments["target_id"])
        chain = active_corpus.resolve_governance_chain(target_id)
        return {
            "rows": [
                {
                    "row_id": f"governance-chain:{target_id}",
                    "values": {
                        "ontology_release_digest": ontology_release.digest,
                        "corpus_digest": active_corpus.corpus_digest,
                        **chain,
                    },
                }
            ],
            "complete": True,
            "truncation_reason": None,
        }

    return evaluate


def catalog_search_cloud_reference_function(
    ontology_release: OntologyRelease,
    *,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> ContextualOntologyFunction:
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
    )
    active_corpus = corpus or load_catalog_knowledge_corpus()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> dict[str, Any]:
        _check_context(invocation_context)
        limit = int(arguments["limit"])
        query = str(arguments.get("query", ""))
        matches = active_corpus.search_cloud_reference(
            query=query,
            resource_type=arguments.get("resource_type"),
            category=arguments.get("category"),
            limit=limit + 1,
        )
        selected = matches[:limit]
        if not selected:
            return {
                "rows": [
                    {
                        "row_id": "cloud_reference:unindexed",
                        "values": {
                            "ontology_release_digest": ontology_release.digest,
                            "corpus_digest": active_corpus.corpus_digest,
                            "query": query,
                            "limitation_code": "cloud_reference_not_indexed",
                            "epistemic_status": "abstained_unindexed_topic",
                            "guidance": (
                                "Topic is not present in the reviewed cloud reference corpus; "
                                "ingest an authoritative document via query.governed_documents."
                            ),
                            "execution_authority": False,
                        },
                    }
                ],
                "complete": True,
                "truncation_reason": None,
            }
        rows = [
            {
                "row_id": f"cloud_reference:{topic.topic_id}",
                "values": {
                    "ontology_release_digest": ontology_release.digest,
                    "corpus_digest": active_corpus.corpus_digest,
                    "topic_id": topic.topic_id,
                    "resource_type": topic.resource_type,
                    "category": topic.category,
                    "title_en": topic.title_en,
                    "title_ko": topic.title_ko,
                    "summary_en": topic.summary_en,
                    "summary_ko": topic.summary_ko,
                    "options": list(topic.options),
                    "cni_models": list(topic.cni_models),
                    "evaluated_property": topic.evaluated_property,
                    "related_rules": list(topic.related_rules),
                    "related_controls": list(topic.related_controls),
                    "related_actions": list(topic.related_actions),
                    "related_workflows": list(topic.related_workflows),
                    "source_url": topic.source_url,
                    "retrieved_at": topic.retrieved_at,
                    "content_digest": topic.content_digest,
                    "epistemic_status": "reviewed_cloud_reference",
                    "execution_authority": False,
                },
            }
            for topic in selected
        ]
        complete = len(matches) <= limit
        return {
            "rows": rows,
            "complete": complete,
            "truncation_reason": None if complete else "result_limit",
        }

    return evaluate


def bind_semantic_catalog_and_decision_functions(
    *,
    registry: OntologyFunctionRegistry,
    declarations: Mapping[str, OntologyFunctionType],
    ontology_release: OntologyRelease,
    ontology_store: OntologyInstanceStore | None = None,
    now: Callable[[], datetime] | None = None,
    corpus: CatalogKnowledgeCorpus | None = None,
) -> None:
    """Bind the 5 catalog/cloud-reference functions in the semantic query runtime."""

    _ = (ontology_store, now)
    active_corpus = corpus or load_catalog_knowledge_corpus()

    bindings: tuple[tuple[str, ContextualOntologyFunction], ...] = (
        (
            CATALOG_SEARCH_WORKFLOWS_FUNCTION_NAME,
            catalog_search_workflows_function(ontology_release, corpus=active_corpus),
        ),
        (
            CATALOG_SEARCH_BUSINESS_SCENARIOS_FUNCTION_NAME,
            catalog_search_business_scenarios_function(ontology_release, corpus=active_corpus),
        ),
        (
            CATALOG_SEARCH_RULES_AND_CONTROLS_FUNCTION_NAME,
            catalog_search_rules_and_controls_function(ontology_release, corpus=active_corpus),
        ),
        (
            CATALOG_RESOLVE_GOVERNANCE_CHAIN_FUNCTION_NAME,
            catalog_resolve_governance_chain_function(ontology_release, corpus=active_corpus),
        ),
        (
            CATALOG_SEARCH_CLOUD_REFERENCE_FUNCTION_NAME,
            catalog_search_cloud_reference_function(ontology_release, corpus=active_corpus),
        ),
    )
    for name, fn_impl in bindings:
        decl = declarations.get(name)
        if decl is not None and name not in registry.binding_authorities:
            registry.register_contextual(
                decl,
                fn_impl,
                authority=EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
            )
