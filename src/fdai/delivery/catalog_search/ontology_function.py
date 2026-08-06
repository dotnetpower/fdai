"""Ontology declaration and strict projection for catalog.search_rules."""

from __future__ import annotations

import hashlib

from fdai.rule_catalog.schema.rule_semantic_generation import CatalogRetrievalReceipt
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionKind,
    OntologyFunctionType,
)

_FUNCTION_NAME = "catalog.search_rules"
_ARTIFACT_ID = b"fdai.catalog.search_rules.v1"
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


def catalog_query_function_type() -> OntologyFunctionType:
    """Return the exact read-only function declaration for concept-first Rule search."""

    string_array = {
        "type": "array",
        "maxItems": 32,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 512},
    }
    return OntologyFunctionType(
        name=_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(_ARTIFACT_ID).hexdigest()}",
        publisher="Mimir",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 4096},
                "operation": {
                    "type": "string",
                    "enum": ["discover", "explain", "evaluate", "action_draft"],
                },
                "corpus": {"type": "string", "enum": ["active", "discovery"]},
                "intent_ids": string_array,
                "concept_refs": string_array,
                "resource_types": string_array,
                "categories": string_array,
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [
                "text",
                "operation",
                "corpus",
                "intent_ids",
                "concept_refs",
                "resource_types",
                "categories",
                "max_results",
            ],
            "additionalProperties": False,
        },
        output_schema=_output_schema(),
        read_sets=["Rule", "PolicyArtifact", "ResourceType", "Property", "ActionType"],
        required_role=CeilingRole.READER,
        purpose_bindings=["rule_lookup"],
        allowed_agents=["Bragi", "Mimir"],
        network_allowed=False,
        credentials_allowed=False,
    )


def project_catalog_retrieval_receipt(receipt: CatalogRetrievalReceipt) -> dict[str, object]:
    """Project a receipt without adding evaluation or execution authority."""

    status = (
        "clarification"
        if receipt.clarification_required
        else "unavailable"
        if receipt.semantic_state.value != "available"
        else "matched"
    )
    return {
        "status": status,
        "receipt_digest": receipt.digest,
        "query_digest": receipt.query_digest,
        "operation": receipt.operation.value,
        "corpus": receipt.corpus.value,
        "catalog_digest": receipt.catalog_digest,
        "generation_digest": receipt.generation_digest,
        "semantic_state": receipt.semantic_state.value,
        "degraded_reason": receipt.degraded_reason,
        "unresolved_terms": list(receipt.unresolved_terms),
        "clarification_required": receipt.clarification_required,
        "truncated": receipt.truncated,
        "execution_authority": False,
        "results": [
            {
                "rule_ref": item.rule_ref,
                "rank": item.rank,
                "components": {name: value for name, value in item.components},
            }
            for item in receipt.results
        ],
    }


def _output_schema() -> dict[str, object]:
    nullable_digest = {
        "anyOf": [
            {"type": "string", "pattern": _DIGEST_PATTERN},
            {"type": "null"},
        ]
    }
    nullable_reason = {
        "anyOf": [
            {"type": "string", "minLength": 1, "maxLength": 512},
            {"type": "null"},
        ]
    }
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["matched", "unavailable", "clarification"]},
            "receipt_digest": {"type": "string", "pattern": _DIGEST_PATTERN},
            "query_digest": {"type": "string", "pattern": _DIGEST_PATTERN},
            "operation": {
                "type": "string",
                "enum": ["discover", "explain", "evaluate", "action_draft"],
            },
            "corpus": {"type": "string", "enum": ["active", "discovery"]},
            "catalog_digest": {"type": "string", "pattern": _DIGEST_PATTERN},
            "generation_digest": nullable_digest,
            "semantic_state": {
                "type": "string",
                "enum": ["available", "stale", "unavailable", "disabled"],
            },
            "degraded_reason": nullable_reason,
            "unresolved_terms": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 512},
            },
            "clarification_required": {"type": "boolean"},
            "truncated": {"type": "boolean"},
            "execution_authority": {"const": False},
            "results": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_ref": {"type": "string", "minLength": 1, "maxLength": 512},
                        "rank": {"type": "integer", "minimum": 1},
                        "components": {
                            "type": "object",
                            "maxProperties": 16,
                            "additionalProperties": {"type": "number"},
                        },
                    },
                    "required": ["rule_ref", "rank", "components"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "status",
            "receipt_digest",
            "query_digest",
            "operation",
            "corpus",
            "catalog_digest",
            "generation_digest",
            "semantic_state",
            "degraded_reason",
            "unresolved_terms",
            "clarification_required",
            "truncated",
            "execution_authority",
            "results",
        ],
        "additionalProperties": False,
    }


__all__ = ["catalog_query_function_type", "project_catalog_retrieval_receipt"]
