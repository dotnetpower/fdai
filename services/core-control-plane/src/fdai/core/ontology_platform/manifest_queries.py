"""Read-only principal-manifest queries over one exact ontology release."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_manifest import QueryManifest

ONTOLOGY_MANIFEST_FUNCTION_NAME = "query.manifest"
ONTOLOGY_MANIFEST_PURPOSE = "operations-review"
_MAX_ROWS = 1_000
_KINDS = ("action", "function", "interface", "link", "object")

ManifestForContext = Callable[[CeilingRole, tuple[str, ...]], QueryManifest]


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def ontology_manifest_function_type() -> OntologyFunctionType:
    """Return the declaration for bounded principal-manifest inspection."""

    return OntologyFunctionType(
        name=ONTOLOGY_MANIFEST_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["kinds", "limit"],
            "properties": {
                "kinds": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": len(_KINDS),
                    "uniqueItems": True,
                    "items": {"enum": list(_KINDS)},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
        output_schema={
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
                            "row_id": {"type": "string", "minLength": 1, "maxLength": 512},
                            "values": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "kind",
                                    "name",
                                    "version",
                                    "declaration_digest",
                                    "available",
                                    "execution_authority",
                                ],
                                "properties": {
                                    "kind": {"enum": list(_KINDS)},
                                    "name": {"type": "string"},
                                    "version": {"type": "string"},
                                    "declaration_digest": {
                                        "type": "string",
                                        "pattern": "^sha256:[a-f0-9]{64}$",
                                    },
                                    "available": {"const": True},
                                    "execution_authority": {"const": False},
                                },
                            },
                        },
                    },
                },
                "complete": {"type": "boolean"},
                "truncation_reason": {
                    "type": ["string", "null"],
                    "enum": ["result_limit", "runtime_binding_unavailable", None],
                },
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[ONTOLOGY_MANIFEST_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=524_288,
        network_allowed=False,
        credentials_allowed=False,
    )


def ontology_manifest_function(
    ontology_release: OntologyRelease,
    *,
    manifest_for_context: ManifestForContext,
) -> ContextualOntologyFunction:
    """Bind a role- and purpose-filtered manifest projection to one release."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ONTOLOGY_MANIFEST_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (ONTOLOGY_MANIFEST_PURPOSE,):
            raise PermissionError("ontology manifest purpose does not match invocation context")
        manifest = manifest_for_context(
            invocation_context.caller_role,
            invocation_context.purposes,
        )
        if manifest.release_digest != ontology_release.digest:
            raise ValueError("query manifest release does not match function release")
        kinds = frozenset(str(item) for item in arguments["kinds"])
        matching = tuple(
            descriptor for descriptor in manifest.descriptors if descriptor.get("kind") in kinds
        )
        unavailable = tuple(
            item
            for item in manifest.unavailable
            if item["declaration_id"].partition(":")[0] in kinds
        )
        limit = int(arguments["limit"])
        selected = matching[:limit]
        limited = len(selected) != len(matching)
        truncation_reason = (
            "result_limit" if limited else "runtime_binding_unavailable" if unavailable else None
        )
        return {
            "rows": [
                {
                    "row_id": f"{descriptor['kind']}:{descriptor['name']}",
                    "values": {
                        "kind": descriptor["kind"],
                        "name": descriptor["name"],
                        "version": descriptor["version"],
                        "declaration_digest": descriptor["declaration_digest"],
                        "available": True,
                        "execution_authority": False,
                    },
                }
                for descriptor in selected
            ],
            "complete": not limited and not unavailable,
            "truncation_reason": truncation_reason,
        }

    return evaluate


__all__ = [
    "ONTOLOGY_MANIFEST_FUNCTION_NAME",
    "ONTOLOGY_MANIFEST_PURPOSE",
    "ManifestForContext",
    "ontology_manifest_function",
    "ontology_manifest_function_type",
]
