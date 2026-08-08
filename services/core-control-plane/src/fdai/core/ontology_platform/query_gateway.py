"""Secured, bounded projection gateway for ontology ObjectSet materialization.

The gateway narrows each query to its declared purpose, applies the shared
property ACL projection to every returned object, closes links over the
visible endpoint set, and returns an immutable read-only receipt. It never
submits actions, calls providers, or grants execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from fdai.shared.contracts.models import CeilingRole, ContractBase, OntologyObjectType
from fdai.shared.ontology.acl import (
    ProjectionRequest,
    RedactionReason,
    project_graph_snapshot,
)
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot

from .models import (
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
)
from .object_sets import ObjectSetService


class ObjectSetRedactionSummary(ContractBase):
    """Content-free counts describing ACL projection and endpoint closure."""

    objects_with_redactions: int = Field(ge=0)
    redacted_identity_count: int = Field(ge=0)
    access_scope_count: int = Field(ge=0)
    purpose_binding_count: int = Field(ge=0)
    undeclared_property_count: int = Field(ge=0)
    removed_link_count: int = Field(ge=0)


class ObjectSetQueryReceipt(ContractBase):
    """Immutable completeness and redaction receipt with no action authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    caller_role: CeilingRole
    returned_object_count: int = Field(ge=0)
    returned_link_count: int = Field(ge=0)
    truncated: bool
    truncation_reason: ObjectSetTruncationReason | None = None
    redactions: ObjectSetRedactionSummary
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _truncation_reason_matches_state(self) -> ObjectSetQueryReceipt:
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("object-set query receipt truncation state is inconsistent")
        return self


class SecuredObjectSetQueryResult(ContractBase):
    """Projected ObjectSet materialization paired with its immutable receipt."""

    materialization: ObjectSetMaterialization
    receipt: ObjectSetQueryReceipt

    @model_validator(mode="after")
    def _receipt_matches_materialization(self) -> SecuredObjectSetQueryResult:
        graph = self.materialization.graph
        if self.receipt.purpose != self.materialization.definition.purpose:
            raise ValueError("object-set query receipt purpose does not match definition")
        if self.receipt.returned_object_count != len(graph.objects):
            raise ValueError("object-set query receipt object count does not match result")
        if self.receipt.returned_link_count != len(graph.links):
            raise ValueError("object-set query receipt link count does not match result")
        if self.receipt.truncated != self.materialization.truncated:
            raise ValueError("object-set query receipt truncation does not match result")
        if self.receipt.truncation_reason != self.materialization.truncation_reason:
            raise ValueError("object-set query receipt truncation reason does not match result")
        return self


class SecuredObjectSetQueryGateway:
    """Materialize one bounded ObjectSet through shared role and purpose ACLs.

    The caller must declare the definition's purpose. Extra caller purposes are
    discarded for projection, so one query cannot combine purposes to widen its
    property view. Missing ObjectType declarations fail closed through the
    shared projector before any result is returned.
    """

    def __init__(
        self,
        *,
        service: ObjectSetService,
        object_types: Mapping[str, OntologyObjectType],
    ) -> None:
        copied_types: dict[str, OntologyObjectType] = {}
        for name, declaration in object_types.items():
            if name != declaration.name:
                raise ValueError("ontology ObjectType registry key MUST match declaration name")
            copied_types[name] = declaration.model_copy(deep=True)
        self._service = service
        self._object_types = MappingProxyType(copied_types)

    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
    ) -> SecuredObjectSetQueryResult:
        """Return a purpose-narrowed ACL projection and no-authority receipt."""

        if definition.purpose not in projection_request.declared_purposes:
            raise PermissionError("object-set query purpose was not declared by the caller")
        effective_request = ProjectionRequest(
            caller_role=projection_request.caller_role,
            declared_purposes=frozenset({definition.purpose}),
        )
        materialization = await self._service.materialize(definition)
        projected_graph = project_graph_snapshot(
            materialization.graph,
            object_types=self._object_types,
            request=effective_request,
        )
        secured_graph = _close_links(projected_graph)
        secured_materialization = ObjectSetMaterialization(
            definition=materialization.definition,
            graph=secured_graph,
            concrete_types=materialization.concrete_types,
            truncated=materialization.truncated,
            truncation_reason=materialization.truncation_reason,
        )
        summary = _summarize_redactions(
            secured_graph,
            object_types=self._object_types,
            removed_link_count=len(materialization.graph.links) - len(secured_graph.links),
        )
        receipt = ObjectSetQueryReceipt(
            purpose=definition.purpose,
            caller_role=effective_request.caller_role,
            returned_object_count=len(secured_graph.objects),
            returned_link_count=len(secured_graph.links),
            truncated=secured_materialization.truncated,
            truncation_reason=secured_materialization.truncation_reason,
            redactions=summary,
        )
        return SecuredObjectSetQueryResult(
            materialization=secured_materialization,
            receipt=receipt,
        )


def _close_links(graph: OntologyGraphSnapshot) -> OntologyGraphSnapshot:
    visible_ids = {record.id for record in graph.objects}
    return OntologyGraphSnapshot(
        objects=graph.objects,
        links=tuple(
            link
            for link in graph.links
            if link.from_id in visible_ids and link.to_id in visible_ids
        ),
        truncated=graph.truncated,
    )


def _summarize_redactions(
    graph: OntologyGraphSnapshot,
    *,
    object_types: Mapping[str, OntologyObjectType],
    removed_link_count: int,
) -> ObjectSetRedactionSummary:
    objects_with_redactions = 0
    redacted_identity_count = 0
    access_scope_count = 0
    purpose_binding_count = 0
    undeclared_property_count = 0
    for record in graph.objects:
        raw_redactions = record.properties.get("__redactions__")
        if not isinstance(raw_redactions, Mapping):
            continue
        objects_with_redactions += 1
        declaration = object_types[record.object_type]
        if declaration.key in raw_redactions:
            redacted_identity_count += 1
        for details in raw_redactions.values():
            if not isinstance(details, Mapping):
                continue
            reason = details.get("reason")
            if reason == RedactionReason.ACCESS_SCOPE.value:
                access_scope_count += 1
            elif reason == RedactionReason.PURPOSE_BINDING.value:
                purpose_binding_count += 1
            elif reason == RedactionReason.UNDECLARED_PROPERTY.value:
                undeclared_property_count += 1
    return ObjectSetRedactionSummary(
        objects_with_redactions=objects_with_redactions,
        redacted_identity_count=redacted_identity_count,
        access_scope_count=access_scope_count,
        purpose_binding_count=purpose_binding_count,
        undeclared_property_count=undeclared_property_count,
        removed_link_count=removed_link_count,
    )


__all__ = [
    "ObjectSetQueryReceipt",
    "ObjectSetRedactionSummary",
    "SecuredObjectSetQueryGateway",
    "SecuredObjectSetQueryResult",
]
