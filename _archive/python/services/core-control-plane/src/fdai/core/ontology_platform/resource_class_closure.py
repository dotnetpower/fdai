"""Exact-release receipts for deterministic ResourceClass expansion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from fdai.rule_catalog.schema.resource_class import ResourceClassRegistry
from fdai.shared.contracts.models import (
    CeilingRole,
    ContractBase,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

RESOURCE_CLASS_CLOSURE_FUNCTION_NAME = "query.resource_class_closure"
RESOURCE_CLASS_CLOSURE_PURPOSE = "operations-review"


class ResourceClassClosureReceipt(ContractBase):
    """Replay-stable concrete ResourceType expansion with no action authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    ontology_release_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    registry_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    registry_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    resource_class_id: Annotated[str, Field(min_length=1, max_length=64)]
    class_ids: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...]
    resource_type_ids: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    closure_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    complete: Literal[True] = True
    execution_authority: Literal[False] = False


def compile_resource_class_closure(
    *,
    registry: ResourceClassRegistry,
    resource_class_id: str,
    ontology_release_digest: str,
) -> ResourceClassClosureReceipt:
    """Compile one reviewed class into exact ResourceType ids and a content digest."""

    class_ids = registry.class_closure(resource_class_id)
    resource_type_ids = registry.closure(resource_class_id)
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": ontology_release_digest,
        "registry_version": registry.version,
        "registry_digest": registry.content_digest,
        "resource_class_id": resource_class_id,
        "class_ids": class_ids,
        "resource_type_ids": resource_type_ids,
        "complete": True,
        "execution_authority": False,
    }
    canonical = json.dumps(
        body,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ResourceClassClosureReceipt(
        ontology_release_digest=ontology_release_digest,
        registry_version=registry.version,
        registry_digest=registry.content_digest,
        resource_class_id=resource_class_id,
        class_ids=class_ids,
        resource_type_ids=resource_type_ids,
        closure_digest="sha256:" + hashlib.sha256(canonical).hexdigest(),
    )


def resource_class_closure_function_type() -> OntologyFunctionType:
    """Return the no-authority exact taxonomy closure FunctionType."""

    digest = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    digest_pattern = "^sha256:[a-f0-9]{64}$"
    return OntologyFunctionType(
        name=RESOURCE_CLASS_CLOSURE_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=digest,
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["resource_class_id"],
            "properties": {
                "resource_class_id": {
                    "type": "string",
                    "pattern": "^class\\.[a-z][a-z0-9-]{0,57}$",
                    "maxLength": 64,
                }
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": list(ResourceClassClosureReceipt.model_fields),
            "properties": {
                "schema_version": {"const": "1.0.0"},
                "ontology_release_digest": {"type": "string", "pattern": digest_pattern},
                "registry_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
                "registry_digest": {"type": "string", "pattern": digest_pattern},
                "resource_class_id": {"type": "string"},
                "class_ids": {
                    "type": "array",
                    "maxItems": 256,
                    "items": {"type": "string"},
                },
                "resource_type_ids": {
                    "type": "array",
                    "maxItems": 256,
                    "items": {"type": "string"},
                },
                "closure_digest": {"type": "string", "pattern": digest_pattern},
                "complete": {"const": True},
                "execution_authority": {"const": False},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[RESOURCE_CLASS_CLOSURE_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_class_closure_function(
    ontology_release: OntologyRelease,
    *,
    registry: ResourceClassRegistry,
) -> ContextualOntologyFunction:
    """Bind one reviewed taxonomy registry to an exact ontology release."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_CLASS_CLOSURE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, object],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (RESOURCE_CLASS_CLOSURE_PURPOSE,):
            raise PermissionError("ResourceClass closure purpose does not match invocation context")
        receipt = compile_resource_class_closure(
            registry=registry,
            resource_class_id=str(arguments["resource_class_id"]),
            ontology_release_digest=ontology_release.digest,
        )
        return receipt.model_dump(mode="json")

    return evaluate


__all__ = [
    "RESOURCE_CLASS_CLOSURE_FUNCTION_NAME",
    "RESOURCE_CLASS_CLOSURE_PURPOSE",
    "ResourceClassClosureReceipt",
    "compile_resource_class_closure",
    "resource_class_closure_function",
    "resource_class_closure_function_type",
]
