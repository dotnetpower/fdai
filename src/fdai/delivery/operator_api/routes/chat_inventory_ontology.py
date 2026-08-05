"""Ontology declaration for the verified inventory selection function."""

from __future__ import annotations

import hashlib

from fdai.delivery.operator_api.routes.chat_inventory_query import (
    inventory_query_argument_schema,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionKind,
    OntologyFunctionType,
)

_FUNCTION_NAME = "inventory.select_resources"
_ARTIFACT_ID = b"fdai.inventory.select_resources.v2"
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


def inventory_query_function_type() -> OntologyFunctionType:
    """Return the exact read-only function declaration used by semantic plans."""

    return OntologyFunctionType(
        name=_FUNCTION_NAME,
        version="1.1.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(_ARTIFACT_ID).hexdigest()}",
        publisher="FDAI",
        input_schema=inventory_query_argument_schema(),
        output_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["matched", "partial", "unavailable", "clarification"],
                },
                "query": {
                    "anyOf": [inventory_query_argument_schema(), {"type": "null"}],
                },
                "reason": {"type": "string", "minLength": 1, "maxLength": 256},
                "resource_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 256},
                },
                "semantic_candidates": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["state", "operation"]},
                            "concept_id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 128,
                            },
                            "score": {"type": "number", "minimum": 0, "maximum": 1},
                            "catalog_digest": {
                                "type": "string",
                                "pattern": _DIGEST_PATTERN,
                            },
                            "target_ref": {
                                "type": "object",
                                "properties": {
                                    "kind": {"const": "function"},
                                    "name": {"const": _FUNCTION_NAME},
                                    "version": {
                                        "type": "string",
                                        "pattern": r"^\d+\.\d+\.\d+$",
                                    },
                                    "catalog_digest": {
                                        "type": "string",
                                        "pattern": _DIGEST_PATTERN,
                                    },
                                },
                                "required": ["kind", "name", "version", "catalog_digest"],
                                "additionalProperties": False,
                            },
                            "input_digest": {
                                "type": "string",
                                "pattern": _DIGEST_PATTERN,
                            },
                            "candidate_digest": {
                                "type": "string",
                                "pattern": _DIGEST_PATTERN,
                            },
                            "labels": {
                                "type": "object",
                                "maxProperties": 8,
                                "propertyNames": {"pattern": r"^[a-z]{2,8}$"},
                                "additionalProperties": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 256,
                                },
                            },
                            "authority": {"const": "candidate_only"},
                        },
                        "required": [
                            "kind",
                            "concept_id",
                            "score",
                            "catalog_digest",
                            "target_ref",
                            "input_digest",
                            "candidate_digest",
                            "labels",
                            "authority",
                        ],
                        "additionalProperties": False,
                    },
                },
                "matched_count": {"type": "integer", "minimum": 0},
                "resources": {
                    "type": "array",
                    "maxItems": 40,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "maxLength": 1024},
                            "type": {"type": "string", "maxLength": 256},
                            "provider_type": {
                                "type": ["string", "null"],
                                "maxLength": 512,
                            },
                            "status": {"type": ["string", "null"], "maxLength": 256},
                            "location": {"type": ["string", "null"], "maxLength": 256},
                            "resource_group": {
                                "type": ["string", "null"],
                                "maxLength": 1024,
                            },
                        },
                        "required": ["name", "type"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["status"],
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "clarification"}}},
                    "then": {
                        "required": [
                            "status",
                            "reason",
                            "query",
                            "resource_types",
                            "semantic_candidates",
                        ]
                    },
                }
            ],
            "additionalProperties": False,
        },
        read_sets=["Resource"],
        required_role=CeilingRole.READER,
        purpose_bindings=["inventory_read"],
        allowed_agents=["Bragi"],
        timeout_seconds=30,
        network_allowed=False,
        credentials_allowed=False,
    )


__all__ = ["inventory_query_function_type"]
