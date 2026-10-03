"""Typed semantic constraints with membership established by current secured ObjectSets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.catalog_search import (
    CatalogSearchDocument,
    catalog_search_document_digest,
)

from .generation import _runtime_object_documents
from .ontology_candidate_authorization import projected_candidate_record
from .ontology_snapshot_store import OntologyStagedProjection
from .ontology_vector_store import _check_deadline

_Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
_Identifier = Annotated[str, Field(min_length=1, max_length=512)]
SELECTION_STRATEGY = "secured-objectset-membership.v1"


class OntologyCandidateClause(BaseModel):
    """One typed conjunction; clauses are unioned, never inferred from query words."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    object_type: str = Field(min_length=1, max_length=256)
    predicates: tuple[ObjectPredicate, ...] = Field(default=(), max_length=16)
    object_ids: tuple[_Identifier, ...] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique_ids(self) -> OntologyCandidateClause:
        if self.object_ids is not None and len(self.object_ids) != len(set(self.object_ids)):
            raise ValueError("ontology candidate clause object ids must be unique")
        return self


class OntologyCandidateSelection(BaseModel):
    """Service-bound semantic input, not proof of meaning, qualification or authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    query_digest: _Digest
    manifest_digest: _Digest
    snapshot_digest: _Digest
    clauses: tuple[OntologyCandidateClause, ...] = Field(min_length=1, max_length=8)

    @classmethod
    def bind(
        cls,
        *,
        query: str,
        manifest: QueryManifest,
        staged: OntologyStagedProjection,
        clauses: Sequence[OntologyCandidateClause],
    ) -> OntologyCandidateSelection:
        return cls(
            query_digest=content_digest({"query": query}),
            manifest_digest=manifest.manifest_digest,
            snapshot_digest=staged.snapshot_digest,
            clauses=tuple(clauses),
        )


@dataclass(frozen=True, slots=True)
class SelectedOntologyCandidates:
    documents: tuple[CatalogSearchDocument, ...]
    query_receipt_digests: tuple[str, ...]
    selection_digest: str


async def resolve_candidate_selection(
    *,
    selection: OntologyCandidateSelection,
    query: str,
    staged: OntologyStagedProjection,
    manifest: QueryManifest,
    documents: tuple[CatalogSearchDocument, ...],
    gateway: SecuredObjectSetQueryGateway,
    as_of: datetime,
    deadline: float,
    resource_type_query_terms: Mapping[str, Sequence[str]],
) -> SelectedOntologyCandidates:
    """Resolve every clause or hold; models cannot set scope, time, limits or relationships.

    Each of at most eight ObjectSets must be complete within 1,000 rows. Current
    projected content must match the prepared snapshot before membership is accepted.
    Predicate ACL checks remain in the secured gateway. No model or embedder is called.
    """
    encoded = selection.model_dump_json()
    if len(encoded.encode("utf-8")) > 32_768:
        raise ValueError("ontology candidate selection exceeds its input bound")
    selection = OntologyCandidateSelection.model_validate_json(encoded)
    selection_digest = content_digest(
        {"strategy": SELECTION_STRATEGY, "selection": selection.model_dump(mode="json")}
    )
    readable_types = {
        str(item["name"]) for item in manifest.descriptors if item["kind"] == "object"
    }
    if (
        len(manifest.purposes) != 1
        or selection.query_digest != content_digest({"query": query})
        or selection.manifest_digest != manifest.manifest_digest
        or selection.snapshot_digest != staged.snapshot_digest
        or any(clause.object_type not in readable_types for clause in selection.clauses)
    ):
        raise ValueError("ontology candidate selection binding or ObjectType mismatch")
    projection = ProjectionRequest(
        caller_role=manifest.principal_role,
        declared_purposes=frozenset(manifest.purposes),
        principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
    )
    indexed = {document.rule_id: document for document in documents}
    matched: dict[str, CatalogSearchDocument] = {}
    receipts: list[str] = []
    for clause in selection.clauses:
        _check_deadline(deadline)
        definition = ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=clause.object_type),
            predicates=clause.predicates,
            object_ids=clause.object_ids,
            as_of=as_of,
            purpose=manifest.purposes[0],
            limit=1000,
            include_relationships=False,
        )
        result = await gateway.materialize(definition, projection_request=projection)
        _check_deadline(deadline)
        receipt = result.receipt
        if (
            result.materialization.definition != definition
            or result.materialization.concrete_types != (clause.object_type,)
            or not receipt.complete
            or receipt.truncated
            or not receipt.source_complete
            or receipt.redactions.redacted_identity_count
            or receipt.source_generation != staged.source_generation
            or receipt.ontology_release.digest != manifest.release_digest
            or receipt.principal_scope_digest != projection.principal_scope_digest
            or receipt.caller_role != manifest.principal_role
            or receipt.purpose != manifest.purposes[0]
        ):
            raise ValueError("ontology candidate selection requires complete current evidence")
        current = _runtime_object_documents(
            tuple(
                projected_candidate_record(record)
                for record in result.materialization.graph.objects
            ),
            manifest=manifest,
            resource_type_query_terms=resource_type_query_terms,
        )
        for document in current:
            _check_deadline(deadline)
            prepared = indexed.get(document.rule_id)
            if prepared is None or catalog_search_document_digest(
                prepared
            ) != catalog_search_document_digest(document):
                raise ValueError("ontology candidate selection source content changed")
            matched[document.rule_id] = prepared
        receipts.append(content_digest(result.receipt.model_dump(mode="json")))
    _check_deadline(deadline)
    return SelectedOntologyCandidates(
        tuple(matched[key] for key in sorted(matched)),
        tuple(dict.fromkeys(receipts)),
        selection_digest,
    )
