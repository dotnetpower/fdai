"""Ontology declaration for the verified inventory selection function."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

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
_FUNCTION_RESULT_STATUSES = frozenset({"matched", "partial", "unavailable", "clarification"})


def project_inventory_function_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project rich chat evidence into the strict ontology function boundary."""

    status = result.get("status")
    if status not in _FUNCTION_RESULT_STATUSES:
        raise ValueError("inventory function result status is invalid")
    query = result.get("query")
    projected: dict[str, Any] = {
        "status": status,
        "query": dict(query) if isinstance(query, Mapping) else None,
    }
    reason = result.get("reason")
    if isinstance(reason, str) and reason:
        projected["reason"] = reason
    if status in {"matched", "partial"}:
        matched_count = result.get("matched_count")
        resources = result.get("resources")
        if not isinstance(matched_count, int) or isinstance(matched_count, bool):
            raise ValueError("inventory function matched_count is invalid")
        if not isinstance(resources, (list, tuple)):
            raise ValueError("inventory function resources are invalid")
        projected["matched_count"] = matched_count
        projected["resources"] = [
            {
                key: resource[key]
                for key in (
                    "name",
                    "type",
                    "provider_type",
                    "status",
                    "location",
                    "resource_group",
                )
                if key in resource
            }
            for resource in resources[:40]
            if isinstance(resource, Mapping)
        ]
    if status == "unavailable" and "reason" not in projected:
        raise ValueError("unavailable inventory function result requires reason")
    if status == "clarification":
        resource_types = result.get("resource_types")
        candidates = result.get("semantic_candidates")
        if not isinstance(resource_types, (list, tuple)) or not isinstance(
            candidates, (list, tuple)
        ):
            raise ValueError("inventory function clarification evidence is invalid")
        projected["resource_types"] = list(resource_types)
        projected["semantic_candidates"] = [
            dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)
        ]
    errors = list(
        Draft202012Validator(inventory_query_function_type().output_schema).iter_errors(projected)
    )
    if errors:
        raise ValueError("inventory function result violates output_schema")
    return projected


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
                    "if": {"properties": {"status": {"enum": ["matched", "partial"]}}},
                    "then": {"required": ["status", "query", "matched_count", "resources"]},
                },
                {
                    "if": {"properties": {"status": {"const": "unavailable"}}},
                    "then": {"required": ["status", "query", "reason"]},
                },
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
                },
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


__all__ = ["inventory_query_function_type", "project_inventory_function_result"]
