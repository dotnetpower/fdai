"""Read-only Rule catalog functions over exact semantic generations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai.rule_catalog.schema.rule_semantic_generation import (
    CatalogRetrievalReceipt,
    RetrievalOperation,
    RetrievalRank,
    SemanticAvailability,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.catalog_search import CatalogSemanticIndex

from .functions import ContextualOntologyFunction, FunctionInvocationContext

CATALOG_SEARCH_RULES_FUNCTION_NAME = "catalog.search_rules"
CATALOG_SEARCH_PURPOSE = "operations-review"


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def catalog_search_rules_function_type() -> OntologyFunctionType:
    """Return the exact read-only candidate-retrieval declaration."""

    return OntologyFunctionType(
        name=CATALOG_SEARCH_RULES_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "operation", "corpus", "limit"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4096},
                "operation": {"enum": ["discover", "explain", "evaluate", "action_draft"]},
                "corpus": {"enum": ["active", "discovery"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "candidates",
                "retrieval_receipt",
                "retrieval_receipt_digest",
                "authority",
                "execution_authority",
            ],
            "properties": {
                "candidates": {"type": "array", "maxItems": 20},
                "retrieval_receipt": {"type": "object"},
                "retrieval_receipt_digest": {
                    "type": "string",
                    "pattern": "^sha256:[a-f0-9]{64}$",
                },
                "authority": {"const": "candidate_only"},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Rule"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[CATALOG_SEARCH_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def catalog_search_rules_function(
    ontology_release: OntologyRelease,
    *,
    index: CatalogSemanticIndex,
    catalog_digest: str,
) -> ContextualOntologyFunction:
    """Bind Rule retrieval to one catalog and ontology release identity."""

    expected_release_digest = ontology_release.digest

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (CATALOG_SEARCH_PURPOSE,):
            raise PermissionError("catalog search purpose does not match invocation context")
        query = str(arguments["query"]).strip()
        if not query:
            raise ValueError("catalog search query MUST be non-empty")
        operation = RetrievalOperation(str(arguments["operation"]))
        corpus = RuleCorpus(str(arguments["corpus"]))
        limit = int(arguments["limit"])
        active = await index.active_generation(corpus.value)
        if active is None or active.state != "active":
            raise RuntimeError("catalog semantic generation is unavailable")
        if (
            active.catalog_digest != catalog_digest
            or active.ontology_release_digest != expected_release_digest
        ):
            raise RuntimeError("catalog semantic generation identity is stale")
        results = await index.search(
            query,
            k=limit,
            corpus=corpus.value,
            expected_catalog_digest=catalog_digest,
        )
        for result in results:
            if (
                result.document_kind != "rule"
                or result.corpus != corpus.value
                or result.generation_id != active.generation_id
                or result.generation_digest != active.generation_digest
                or result.catalog_digest != catalog_digest
            ):
                raise RuntimeError("catalog semantic result identity is invalid")
        ranks = tuple(
            RetrievalRank(
                rule_ref=result.rule_id,
                rank=rank,
                components=tuple(sorted(result.components.items())),
            )
            for rank, result in enumerate(results, start=1)
        )
        receipt = CatalogRetrievalReceipt(
            query_digest=_query_digest(
                query=query,
                operation=operation,
                corpus=corpus,
                limit=limit,
            ),
            operation=operation,
            corpus=corpus,
            catalog_digest=catalog_digest,
            semantic_state=SemanticAvailability.AVAILABLE,
            results=ranks,
            generation_digest=active.generation_digest,
        )
        return {
            "candidates": [
                {
                    "rule_ref": item.rule_ref,
                    "rank": item.rank,
                    "components": dict(item.components),
                    "authority": "candidate_only",
                }
                for item in ranks
            ],
            "retrieval_receipt": _receipt_payload(receipt),
            "retrieval_receipt_digest": receipt.digest,
            "authority": "candidate_only",
            "execution_authority": False,
        }

    return evaluate


def _query_digest(
    *,
    query: str,
    operation: RetrievalOperation,
    corpus: RuleCorpus,
    limit: int,
) -> str:
    payload = {
        "query": query,
        "operation": operation.value,
        "corpus": corpus.value,
        "limit": limit,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _receipt_payload(receipt: CatalogRetrievalReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "query_digest": receipt.query_digest,
        "operation": receipt.operation.value,
        "corpus": receipt.corpus.value,
        "catalog_digest": receipt.catalog_digest,
        "semantic_state": receipt.semantic_state.value,
        "generation_digest": receipt.generation_digest,
        "results": [
            {
                "rule_ref": item.rule_ref,
                "rank": item.rank,
                "components": dict(item.components),
            }
            for item in receipt.results
        ],
        "degraded_reason": receipt.degraded_reason,
        "unresolved_terms": list(receipt.unresolved_terms),
        "clarification_required": receipt.clarification_required,
        "truncated": receipt.truncated,
        "execution_authority": receipt.execution_authority,
    }


__all__ = [
    "CATALOG_SEARCH_PURPOSE",
    "CATALOG_SEARCH_RULES_FUNCTION_NAME",
    "catalog_search_rules_function",
    "catalog_search_rules_function_type",
]
