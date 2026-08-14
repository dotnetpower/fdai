"""Read-only instance relationship queries over one secured ontology snapshot."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field

from fdai.shared.contracts.models import (
    CeilingRole,
    ContractBase,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
    OntologyReleaseRef,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryReceipt, SecuredObjectSetQueryResult

INSTANCE_RELATIONSHIPS_FUNCTION_NAME = "query.instance_relationships"
INSTANCE_RELATIONSHIPS_PURPOSE = "operations-review"
_MAX_LINK_TYPES = 64
_MAX_RELATIONSHIPS = 100


class InstanceRelationshipReceiptVerifier(Protocol):
    """Authenticate one secured query receipt against an opaque trust context."""

    def verify(
        self,
        *,
        receipt: SecuredObjectSetQueryReceipt,
        invocation_context: FunctionInvocationContext,
        expected_release: OntologyReleaseRef,
        expected_purpose: str,
        expected_result_digest: str,
        verification_context: object,
    ) -> bool: ...


class InstanceRelationship(ContractBase):
    """One stored directed relationship between visible ontology instances."""

    link_type: Annotated[str, Field(min_length=1, max_length=64)]
    from_id: Annotated[str, Field(min_length=1, max_length=512)]
    from_type: Annotated[str, Field(min_length=1, max_length=128)]
    to_id: Annotated[str, Field(min_length=1, max_length=512)]
    to_type: Annotated[str, Field(min_length=1, max_length=128)]


class InstanceRelationshipResult(ContractBase):
    """Bounded relationship rows with closed-population completeness evidence."""

    link_types: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=64)], ...],
        Field(min_length=1, max_length=_MAX_LINK_TYPES),
    ]
    relationships: Annotated[
        tuple[InstanceRelationship, ...], Field(max_length=_MAX_RELATIONSHIPS)
    ] = ()
    complete: bool
    truncation_reasons: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = ()
    ontology_release: OntologyReleaseRef
    query_result_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    execution_authority: Literal[False] = False


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def instance_relationships_function_type() -> OntologyFunctionType:
    """Return the exact read-only deterministic FunctionType declaration."""

    return OntologyFunctionType(
        name=INSTANCE_RELATIONSHIPS_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "link_types", "limit"],
            "properties": {
                "query_result": {"type": "object"},
                "link_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_LINK_TYPES,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 64},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_RELATIONSHIPS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "link_types",
                "relationships",
                "complete",
                "truncation_reasons",
                "ontology_release",
                "query_result_digest",
                "execution_authority",
            ],
            "properties": {
                "link_types": {"type": "array", "maxItems": _MAX_LINK_TYPES},
                "relationships": {"type": "array", "maxItems": _MAX_RELATIONSHIPS},
                "complete": {"type": "boolean"},
                "truncation_reasons": {"type": "array"},
                "ontology_release": {"type": "object"},
                "query_result_digest": {
                    "type": "string",
                    "pattern": "^sha256:[a-f0-9]{64}$",
                },
                "execution_authority": {"const": False},
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[INSTANCE_RELATIONSHIPS_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def instance_relationships_function(
    ontology_release: OntologyRelease,
    *,
    known_link_types: Sequence[str],
    receipt_verifier: InstanceRelationshipReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind a receipt-authenticated current relationship query to one release."""

    if verification_context is None:
        raise ValueError("instance relationship receipt verification context MUST be non-null")
    expected_release = ontology_release.ref()
    known = frozenset(known_link_types)

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        query_result = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        receipt = query_result.receipt
        expected_digest = receipt.projected_result_digest
        if receipt.ontology_release != expected_release:
            raise ValueError(
                "instance relationship query result does not match the exact ontology release"
            )
        if (
            receipt.caller_role != invocation_context.caller_role
            or receipt.purpose != INSTANCE_RELATIONSHIPS_PURPOSE
            or invocation_context.purposes != (INSTANCE_RELATIONSHIPS_PURPOSE,)
            or invocation_context.evidence_refs != (expected_digest,)
        ):
            raise PermissionError(
                "instance relationship query receipt does not match invocation context"
            )
        if not receipt_verifier.verify(
            receipt=receipt,
            invocation_context=invocation_context,
            expected_release=expected_release,
            expected_purpose=INSTANCE_RELATIONSHIPS_PURPOSE,
            expected_result_digest=expected_digest,
            verification_context=verification_context,
        ):
            raise PermissionError("instance relationship query receipt verification failed")

        requested = tuple(str(item) for item in arguments["link_types"])
        if len(requested) != len(set(requested)) or any(item not in known for item in requested):
            raise ValueError("instance relationship LinkType is absent from the release")
        return evaluate_instance_relationships(
            query_result,
            link_types=requested,
            limit=int(arguments["limit"]),
        ).model_dump(mode="json")

    return evaluate


def evaluate_instance_relationships(
    query_result: SecuredObjectSetQueryResult,
    *,
    link_types: Sequence[str],
    limit: int,
) -> InstanceRelationshipResult:
    """Filter stored directed links while preserving source completeness."""

    secured = SecuredObjectSetQueryResult.model_validate(query_result.model_dump(mode="json"))
    requested = tuple(link_types)
    if not 1 <= len(requested) <= _MAX_LINK_TYPES or len(requested) != len(set(requested)):
        raise ValueError("instance relationship LinkTypes MUST be unique and bounded")
    if not 1 <= limit <= _MAX_RELATIONSHIPS:
        raise ValueError("instance relationship limit MUST be between 1 and 100")

    objects = {item.id: item for item in secured.materialization.graph.objects}
    matching = tuple(
        link for link in secured.materialization.graph.links if link.link_type in set(requested)
    )
    selected = matching[:limit]
    source_complete = secured.receipt.complete
    result_complete = source_complete and len(selected) == len(matching)
    reasons: list[str] = []
    if not source_complete:
        reasons.append(
            secured.receipt.truncation_reason.value
            if secured.receipt.truncation_reason is not None
            else "source_incomplete"
        )
    if len(selected) != len(matching):
        reasons.append("relationship_limit")

    return InstanceRelationshipResult(
        link_types=requested,
        relationships=tuple(
            InstanceRelationship(
                link_type=link.link_type,
                from_id=link.from_id,
                from_type=objects[link.from_id].object_type,
                to_id=link.to_id,
                to_type=objects[link.to_id].object_type,
            )
            for link in selected
        ),
        complete=result_complete,
        truncation_reasons=tuple(reasons),
        ontology_release=secured.receipt.ontology_release,
        query_result_digest=secured.receipt.projected_result_digest,
    )


__all__ = [
    "INSTANCE_RELATIONSHIPS_FUNCTION_NAME",
    "INSTANCE_RELATIONSHIPS_PURPOSE",
    "InstanceRelationship",
    "InstanceRelationshipResult",
    "evaluate_instance_relationships",
    "instance_relationships_function",
    "instance_relationships_function_type",
]
