"""Reauthorize indexed object candidates through current secured graph reads."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.models import (
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
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .generation import _runtime_object_documents
from .ontology_snapshot_store import OntologyStagedProjection


@dataclass(frozen=True, slots=True)
class AuthorizedOntologyCandidates:
    """Current graph facts and their receipt identities, never index-authored facts."""

    objects: tuple[OntologyObjectRecord, ...]
    query_receipt_digests: tuple[str, ...]
    snapshot_digest: str
    source_generation: str
    principal_scope_digest: str

    @property
    def result_digest(self) -> str:
        return content_digest(
            {
                "objects": [
                    {
                        "id": record.id,
                        "object_type": record.object_type,
                        "properties": dict(record.properties),
                    }
                    for record in self.objects
                ],
                "query_receipt_digests": self.query_receipt_digests,
                "snapshot_digest": self.snapshot_digest,
                "source_generation": self.source_generation,
                "principal_scope_digest": self.principal_scope_digest,
                "execution_authority": False,
            }
        )


async def reauthorize_ontology_candidates(
    *,
    candidates: tuple[CatalogSearchDocument, ...],
    staged: OntologyStagedProjection,
    manifest: QueryManifest,
    gateway: SecuredObjectSetQueryGateway,
    as_of: datetime,
) -> AuthorizedOntologyCandidates:
    """Hold the whole candidate result on deletion, scope, source, or content drift.

    At most 100 candidates and 16 type reads fit inside a five-second deadline.
    Every returned property comes from a current ACL-projected graph. Index text
    is used only for exact comparison; even self-consistent fabricated rows fail.
    """
    if not 1 <= len(candidates) <= 100 or len(manifest.purposes) != 1:
        raise ValueError("ontology candidates require bounded single-purpose reauthorization")
    by_type: dict[str, list[str]] = {}
    expected: dict[tuple[str, str], CatalogSearchDocument] = {}
    readable_types = {
        str(item["name"]) for item in manifest.descriptors if item["kind"] == "object"
    }
    for candidate in candidates:
        try:
            payload = json.loads(candidate.text)
            identifier, type_name = payload["id"], payload["object_type"]
            if (
                candidate.document_kind != "ontology_object"
                or not isinstance(identifier, str)
                or not isinstance(type_name, str)
                or type_name not in readable_types
                or candidate.rule_id != f"object:{type_name}:{identifier}"
                or (type_name, identifier) in expected
            ):
                raise ValueError("invalid candidate")
        except (ValueError, KeyError, TypeError):
            raise ValueError("ontology candidate identity is not in the current manifest") from None
        by_type.setdefault(type_name, []).append(identifier)
        expected[type_name, identifier] = candidate
    if len(by_type) > 16:
        raise ValueError("ontology candidate type bound exceeded")
    observed: dict[tuple[str, str], OntologyObjectRecord] = {}
    receipts: list[str] = []
    async with asyncio.timeout(5):
        for type_name, identifiers in sorted(by_type.items()):
            result = await gateway.materialize(
                ObjectSetDefinition(
                    selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=type_name),
                    object_ids=tuple(identifiers),
                    as_of=as_of,
                    purpose=manifest.purposes[0],
                    include_relationships=False,
                    limit=len(identifiers),
                ),
                projection_request=ProjectionRequest(
                    caller_role=manifest.principal_role,
                    declared_purposes=frozenset(manifest.purposes),
                    principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
                ),
            )
            receipt = result.receipt
            if (
                not receipt.complete
                or receipt.truncated
                or not receipt.source_complete
                or receipt.redactions.redacted_identity_count
                or receipt.source_generation != staged.source_generation
                or receipt.ontology_release.digest != manifest.release_digest
                or receipt.principal_scope_digest
                != manifest.coverage_receipt.principal_scope_digest
                or receipt.caller_role != manifest.principal_role
                or receipt.purpose != manifest.purposes[0]
            ):
                raise ValueError("ontology candidates require current complete authorized evidence")
            receipts.append(content_digest(receipt.model_dump(mode="json")))
            for record in result.materialization.graph.objects:
                key = record.object_type, record.id
                if key not in expected or key in observed:
                    raise ValueError("ontology candidate current graph identity mismatch")
                observed[key] = OntologyObjectRecord(
                    id=record.id,
                    object_type=record.object_type,
                    revision=record.revision,
                    type_ref=record.type_ref,
                    properties=MappingProxyType(
                        {
                            name: value
                            for name, value in record.properties.items()
                            if name != "__redactions__"
                            and name not in record.properties.get("__redactions__", {})
                        }
                    ),
                )
    if observed.keys() != expected.keys():
        raise ValueError("ontology candidate no longer exists in the authorized graph")
    current_digests = {
        item.rule_id: catalog_search_document_digest(item)
        for item in _runtime_object_documents(tuple(observed.values()))
    }
    if any(
        current_digests[item.rule_id] != catalog_search_document_digest(item) for item in candidates
    ):
        raise ValueError("ontology candidate current authorized content mismatch")
    return AuthorizedOntologyCandidates(
        objects=tuple(observed[key] for key in expected),
        query_receipt_digests=tuple(receipts),
        snapshot_digest=staged.snapshot_digest,
        source_generation=staged.source_generation,
        principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
    )
