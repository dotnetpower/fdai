"""Secured, bounded projection gateway for ontology ObjectSet materialization.

The gateway narrows each query to its declared purpose, applies the shared
property ACL projection to every returned object, closes links over the
visible endpoint set, and returns an immutable read-only receipt. It never
submits actions, calls providers, or grants execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    CeilingRole,
    ContractBase,
    OntologyDeclarationKind,
    OntologyObjectType,
    OntologyRelease,
    OntologyReleaseRef,
)
from fdai.shared.ontology.acl import (
    ProjectionRequest,
    RedactionReason,
    project_graph_snapshot,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)

from .functions import ontology_function_digest
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
    links_with_redactions: int = Field(ge=0)
    redacted_link_property_count: int = Field(ge=0)
    removed_link_count: int = Field(ge=0)


class SecuredObjectSetQueryReceipt(ContractBase):
    """Immutable completeness and redaction receipt with no action authority."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    ontology_release: OntologyReleaseRef
    projected_result_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    purpose: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    caller_role: CeilingRole
    observation_cutoff: datetime
    temporal_support: Literal["current_state_only"] = "current_state_only"
    as_of_skew_seconds: float = Field(ge=0, le=5)
    returned_object_count: int = Field(ge=0)
    returned_link_count: int = Field(ge=0)
    complete: bool
    truncated: bool
    truncation_reason: ObjectSetTruncationReason | None = None
    redactions: ObjectSetRedactionSummary
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _truncation_reason_matches_state(self) -> SecuredObjectSetQueryReceipt:
        if self.truncated != (self.truncation_reason is not None):
            raise ValueError("object-set query receipt truncation state is inconsistent")
        if self.complete == self.truncated:
            raise ValueError("object-set query receipt completeness is inconsistent")
        if self.observation_cutoff.tzinfo is None:
            raise ValueError("object-set query observation_cutoff MUST be timezone-aware")
        return self


class SecuredObjectSetQueryResult(ContractBase):
    """Projected ObjectSet materialization paired with its immutable receipt."""

    materialization: ObjectSetMaterialization
    receipt: SecuredObjectSetQueryReceipt

    @model_validator(mode="after")
    def _receipt_matches_materialization(self) -> SecuredObjectSetQueryResult:
        graph = self.materialization.graph
        if self.receipt.purpose != self.materialization.definition.purpose:
            raise ValueError("object-set query receipt purpose does not match definition")
        if self.receipt.projected_result_digest != _projected_result_digest(self.materialization):
            raise ValueError(
                "object-set query receipt projected result digest does not match result"
            )
        if self.receipt.returned_object_count != len(graph.objects):
            raise ValueError("object-set query receipt object count does not match result")
        if self.receipt.returned_link_count != len(graph.links):
            raise ValueError("object-set query receipt link count does not match result")
        if self.receipt.truncated != self.materialization.truncated:
            raise ValueError("object-set query receipt truncation does not match result")
        if self.receipt.truncation_reason != self.materialization.truncation_reason:
            raise ValueError("object-set query receipt truncation reason does not match result")
        if self.receipt.complete == self.materialization.truncated:
            raise ValueError("object-set query receipt completeness does not match result")
        as_of = self.materialization.definition.as_of.astimezone(UTC)
        cutoff = self.receipt.observation_cutoff.astimezone(UTC)
        if abs((as_of - cutoff).total_seconds()) > self.receipt.as_of_skew_seconds:
            raise ValueError("object-set query receipt current-state cutoff does not match result")
        return self


class UnsupportedObjectSetAsOfError(ValueError):
    """A current-state store cannot satisfy the requested historical or future cutoff."""

    temporal_support: Literal["current_state_only"] = "current_state_only"


class SecuredObjectSetQueryReceiptIssuer(Protocol):
    """Seal one gateway-created receipt in a composition-owned trust domain."""

    def issue(self, receipt: SecuredObjectSetQueryReceipt) -> None: ...


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
        ontology_release: OntologyRelease,
        evaluation_cutoff: Callable[[], datetime],
        max_as_of_skew: timedelta = timedelta(0),
        receipt_issuer: SecuredObjectSetQueryReceiptIssuer | None = None,
    ) -> None:
        copied_types: dict[str, OntologyObjectType] = {}
        for name, declaration in object_types.items():
            if name != declaration.name:
                raise ValueError("ontology ObjectType registry key MUST match declaration name")
            copied_types[name] = declaration.model_copy(deep=True)
            active = next(
                (
                    reference
                    for reference in ontology_release.declarations
                    if reference.kind is OntologyDeclarationKind.OBJECT
                    and reference.name == declaration.name
                ),
                None,
            )
            expected = build_ontology_release(object_types=(declaration,)).declarations[0]
            if active != expected:
                raise ValueError("ontology ObjectType declaration does not match release")
        skew_seconds = max_as_of_skew.total_seconds()
        if skew_seconds < 0 or skew_seconds > 5:
            raise ValueError("current-state ObjectSet as_of skew MUST be between 0 and 5 seconds")
        self._service = service
        self._object_types = MappingProxyType(copied_types)
        self._ontology_release = ontology_release.ref()
        self._evaluation_cutoff = evaluation_cutoff
        self._max_as_of_skew_seconds = skew_seconds
        self._receipt_issuer = receipt_issuer

    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
    ) -> SecuredObjectSetQueryResult:
        """Return a purpose-narrowed ACL projection and no-authority receipt."""

        if definition.purpose not in projection_request.declared_purposes:
            raise PermissionError("object-set query purpose was not declared by the caller")
        observation_cutoff = self._evaluation_cutoff()
        if observation_cutoff.tzinfo is None:
            raise ValueError("current-state ObjectSet evaluation cutoff MUST be timezone-aware")
        observation_cutoff = observation_cutoff.astimezone(UTC)
        as_of = definition.as_of.astimezone(UTC)
        if abs((as_of - observation_cutoff).total_seconds()) > self._max_as_of_skew_seconds:
            raise UnsupportedObjectSetAsOfError(
                "current-state ObjectSet as_of is unsupported outside the trusted evaluation "
                "cutoff skew"
            )
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
        secured_graph = _freeze_graph(_close_links(projected_graph))
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
            source_graph=materialization.graph,
            removed_link_count=len(materialization.graph.links) - len(secured_graph.links),
        )
        receipt = SecuredObjectSetQueryReceipt(
            ontology_release=self._ontology_release,
            projected_result_digest=_projected_result_digest(secured_materialization),
            purpose=definition.purpose,
            caller_role=effective_request.caller_role,
            observation_cutoff=observation_cutoff,
            as_of_skew_seconds=self._max_as_of_skew_seconds,
            returned_object_count=len(secured_graph.objects),
            returned_link_count=len(secured_graph.links),
            complete=not secured_materialization.truncated,
            truncated=secured_materialization.truncated,
            truncation_reason=secured_materialization.truncation_reason,
            redactions=summary,
        )
        if self._receipt_issuer is not None:
            self._receipt_issuer.issue(receipt)
        return SecuredObjectSetQueryResult(
            materialization=secured_materialization,
            receipt=receipt,
        )


def _close_links(graph: OntologyGraphSnapshot) -> OntologyGraphSnapshot:
    object_ids = [record.id for record in graph.objects]
    visible_ids = set(object_ids)
    if len(visible_ids) != len(object_ids):
        raise ValueError("secured ObjectSet object ids MUST be unique")
    return OntologyGraphSnapshot(
        objects=graph.objects,
        links=tuple(
            link
            for link in graph.links
            if link.from_id in visible_ids and link.to_id in visible_ids
        ),
        truncated=graph.truncated,
    )


def _freeze_graph(graph: OntologyGraphSnapshot) -> OntologyGraphSnapshot:
    return OntologyGraphSnapshot(
        objects=tuple(
            OntologyObjectRecord(
                id=record.id,
                object_type=record.object_type,
                properties=cast(
                    Mapping[str, Any],
                    _freeze_json(
                        normalize_json_value(
                            record.properties,
                            path=f"secured.{record.object_type}.properties",
                        )
                    ),
                ),
                revision=record.revision,
                type_ref=record.type_ref,
            )
            for record in graph.objects
        ),
        links=tuple(
            OntologyLinkRecord(
                link_type=link.link_type,
                from_id=link.from_id,
                to_id=link.to_id,
                properties=cast(
                    Mapping[str, Any],
                    _freeze_json(
                        normalize_json_value(
                            link.properties,
                            path=f"secured.{link.link_type}.properties",
                        )
                    ),
                ),
                type_ref=link.type_ref,
            )
            for link in graph.links
        ),
        truncated=graph.truncated,
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _ImmutableDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    return value


class _ImmutableDict(dict[str, Any]):
    """JSON-serializable mapping that rejects every post-construction mutation."""

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def clear(self) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    def pop(self, key: str, default: Any = None) -> Any:
        raise TypeError("secured ObjectSet properties are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("secured ObjectSet properties are immutable")

    def setdefault(self, key: str, default: Any = None) -> Any:
        raise TypeError("secured ObjectSet properties are immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("secured ObjectSet properties are immutable")

    # dict's overloaded union signatures cannot express an override that always refuses mutation.
    def __ior__(self, other: object, /) -> _ImmutableDict:  # type: ignore[override,misc]
        raise TypeError("secured ObjectSet properties are immutable")


def _projected_result_digest(materialization: ObjectSetMaterialization) -> str:
    graph = materialization.graph
    return ontology_function_digest(
        {
            "definition": materialization.definition.model_dump(mode="json"),
            "objects": [
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": _mutable_json(record.properties),
                    "revision": record.revision,
                    "type_ref": (
                        record.type_ref.model_dump(mode="json")
                        if record.type_ref is not None
                        else None
                    ),
                }
                for record in graph.objects
            ],
            "links": [
                {
                    "link_type": link.link_type,
                    "from_id": link.from_id,
                    "to_id": link.to_id,
                    "properties": _mutable_json(link.properties),
                    "type_ref": (
                        link.type_ref.model_dump(mode="json") if link.type_ref is not None else None
                    ),
                }
                for link in graph.links
            ],
            "graph_truncated": graph.truncated,
            "concrete_types": list(materialization.concrete_types),
            "truncated": materialization.truncated,
            "truncation_reason": (
                materialization.truncation_reason.value
                if materialization.truncation_reason is not None
                else None
            ),
        }
    )


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_json(item) for item in value]
    return value


def _summarize_redactions(
    graph: OntologyGraphSnapshot,
    *,
    object_types: Mapping[str, OntologyObjectType],
    source_graph: OntologyGraphSnapshot,
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
        links_with_redactions=sum(bool(link.properties) for link in source_graph.links),
        redacted_link_property_count=sum(len(link.properties) for link in source_graph.links),
        removed_link_count=removed_link_count,
    )


ObjectSetQueryReceipt = SecuredObjectSetQueryReceipt


__all__ = [
    "ObjectSetQueryReceipt",
    "ObjectSetRedactionSummary",
    "SecuredObjectSetQueryGateway",
    "SecuredObjectSetQueryReceipt",
    "SecuredObjectSetQueryReceiptIssuer",
    "SecuredObjectSetQueryResult",
    "UnsupportedObjectSetAsOfError",
]
