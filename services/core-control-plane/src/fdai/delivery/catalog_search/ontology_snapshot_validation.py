"""Independent current-graph validation of inactive ontology search snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .generation import build_ontology_semantic_generation, validate_ontology_semantic_generation
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection


@dataclass(frozen=True, slots=True)
class OntologySnapshotValidation:
    """Read-only validation evidence; neither an activation command nor a promotion."""

    snapshot_digest: str
    generation_digest: str
    source_generation: str
    principal_scope_digest: str
    manifest_digest: str
    source_projection_digest: str
    checked_projection_digest: str
    checked_at: datetime
    validator_id: str

    @property
    def receipt_digest(self) -> str:
        return content_digest(
            {
                "schema_version": "1.0.0",
                "snapshot_digest": self.snapshot_digest,
                "generation_digest": self.generation_digest,
                "source_generation": self.source_generation,
                "principal_scope_digest": self.principal_scope_digest,
                "manifest_digest": self.manifest_digest,
                "source_projection_digest": self.source_projection_digest,
                "checked_projection_digest": self.checked_projection_digest,
                "checked_at": self.checked_at.isoformat(),
                "validator_id": self.validator_id,
                "validation_authority": "validation_only",
                "execution_authority": False,
            }
        )


async def validate_snapshot_against_current_graph(
    *,
    snapshots: OntologyGenerationSnapshotStore,
    staged: OntologyStagedProjection,
    gateway: SecuredObjectSetQueryGateway,
    manifest: QueryManifest,
    as_of: datetime,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    validator_id: str,
) -> OntologySnapshotValidation:
    """Rebuild candidates from an independent secured read, not from stored row hashes.

    The caller supplies the authoritative current manifest and expected embedding
    identity. Full manifest scope, source generation, every permitted value, and all
    declarations must agree. Missing, deleted, changed, or fabricated objects hold.
    No persistence, embedding calls, index activation, or privilege change occurs.
    """
    if not validator_id or len(validator_id) > 128 or as_of.tzinfo is None:
        raise ValueError("snapshot validation requires a bounded validator and aware cutoff")
    if len(manifest.purposes) != 1:
        raise ValueError("snapshot validation requires one exact purpose")
    stored = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    if stored is None:
        raise ValueError("snapshot validation requires a complete staged snapshot")
    if any(
        document.embedding or document.generation_id is not None for document in stored.documents
    ):
        raise ValueError(
            "snapshot validation cannot qualify precomputed vectors or index identities"
        )
    if (
        stored.metadata.embedding_space_id,
        stored.metadata.embedding_model_version,
        stored.metadata.embedding_dimension,
    ) != (embedding_space_id, embedding_model_version, embedding_dimension):
        raise ValueError("snapshot validation embedding identity mismatch")
    names = tuple(
        sorted(str(item["name"]) for item in manifest.descriptors if item["kind"] == "object")
    )
    observed = await gateway.scan_snapshot(
        object_type_names=names,
        purpose=manifest.purposes[0],
        as_of=as_of,
        candidate_limit=20_000 - len(manifest.descriptors) - len(manifest.unavailable),
        projection_request=ProjectionRequest(
            caller_role=manifest.principal_role,
            declared_purposes=frozenset(manifest.purposes),
            principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
        ),
    )
    if (
        observed.graph.source_generation != staged.source_generation
        or observed.ontology_release_digest != manifest.release_digest
        or observed.principal_scope_digest != manifest.coverage_receipt.principal_scope_digest
        or observed.caller_role != manifest.principal_role
        or observed.purpose != manifest.purposes[0]
        or observed.object_type_names != names
    ):
        raise ValueError("snapshot validation current source identity mismatch")
    records = tuple(
        OntologyObjectRecord(
            id=record.id,
            object_type=record.object_type,
            properties={
                key: value
                for key, value in record.properties.items()
                if key != "__redactions__"
                and key not in record.properties.get("__redactions__", {})
            },
        )
        for record in observed.graph.objects
    )
    expected = build_ontology_semantic_generation(
        manifest=manifest,
        runtime_objects=records,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
    )
    if (
        stored.document_digests != expected.document_digests
        or stored.metadata.generation_digest != expected.metadata.generation_digest
    ):
        raise ValueError("snapshot validation current source content mismatch")
    validate_ontology_semantic_generation(
        build=stored, manifest=manifest, validator_id=validator_id
    )
    return OntologySnapshotValidation(
        staged.snapshot_digest,
        stored.metadata.generation_digest,
        staged.source_generation,
        manifest.coverage_receipt.principal_scope_digest,
        manifest.manifest_digest,
        staged.source_projection_digest,
        observed.source_projection_digest,
        observed.observation_cutoff,
        validator_id,
    )
