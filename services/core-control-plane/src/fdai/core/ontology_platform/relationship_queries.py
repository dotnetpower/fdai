"""Read-only schema relationship queries over one exact ontology release."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME = "query.ontology_relationships"
ONTOLOGY_RELATIONSHIPS_PURPOSE = "operations-review"
_MAX_OBJECT_TYPES = 2
_MAX_RELATIONSHIPS = 100


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def ontology_relationships_function_type() -> OntologyFunctionType:
    """Return the declaration for exact ObjectType-to-LinkType inspection."""

    return OntologyFunctionType(
        name=ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["object_types", "limit"],
            "properties": {
                "object_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_OBJECT_TYPES,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_RELATIONSHIPS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "object_types",
                "relationships",
                "complete",
                "authority",
                "ontology_release_digest",
                "execution_authority",
            ],
            "properties": {
                "object_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_OBJECT_TYPES,
                    "items": {"type": "string"},
                },
                "relationships": {
                    "type": "array",
                    "maxItems": _MAX_RELATIONSHIPS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "link_type",
                            "from_type",
                            "to_type",
                            "cardinality",
                            "description",
                        ],
                        "properties": {
                            "link_type": {"type": "string"},
                            "from_type": {"type": "string"},
                            "to_type": {"type": "string"},
                            "cardinality": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
                "complete": {"type": "boolean"},
                "authority": {"const": "ontology_release"},
                "ontology_release_digest": {
                    "type": "string",
                    "pattern": "^sha256:[a-f0-9]{64}$",
                },
                "execution_authority": {"const": False},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[ONTOLOGY_RELATIONSHIPS_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def ontology_relationships_function(
    ontology_release: OntologyRelease,
    *,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
) -> ContextualOntologyFunction:
    """Bind immutable ObjectType and LinkType declarations to one release."""

    known_object_types = frozenset(item.name for item in object_types)
    declarations = tuple(sorted(link_types, key=lambda item: item.name))
    for object_type in object_types:
        ontology_release.type_ref(OntologyDeclarationKind.OBJECT, object_type.name)
    for link_type in declarations:
        ontology_release.type_ref(OntologyDeclarationKind.LINK, link_type.name)
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (ONTOLOGY_RELATIONSHIPS_PURPOSE,):
            raise PermissionError("ontology relationship purpose does not match invocation context")
        requested = tuple(str(item) for item in arguments["object_types"])
        if any(item not in known_object_types for item in requested):
            raise ValueError("ontology relationship ObjectType is absent from the release")
        requested_set = frozenset(requested)
        matching = tuple(
            item
            for item in declarations
            if (
                {item.from_type, item.to_type} <= requested_set
                if len(requested_set) == 2
                else item.from_type in requested_set or item.to_type in requested_set
            )
        )
        limit = int(arguments["limit"])
        selected = matching[:limit]
        return {
            "object_types": list(requested),
            "relationships": [
                {
                    "link_type": item.name,
                    "from_type": item.from_type,
                    "to_type": item.to_type,
                    "cardinality": item.cardinality.value,
                    "description": item.description,
                }
                for item in selected
            ],
            "complete": len(selected) == len(matching),
            "authority": "ontology_release",
            "ontology_release_digest": ontology_release.digest,
            "execution_authority": False,
        }

    return evaluate


__all__ = [
    "ONTOLOGY_RELATIONSHIPS_FUNCTION_NAME",
    "ONTOLOGY_RELATIONSHIPS_PURPOSE",
    "ontology_relationships_function",
    "ontology_relationships_function_type",
]
