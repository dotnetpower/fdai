"""Cloud-reference facade that feeds verified candidates into ordinary document ingestion."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from uuid import UUID

from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentVersion,
    SourceStorageMode,
)
from fdai_service_contracts.cloud_knowledge import (
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_admission import validate_admitted_binding
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy, verify_package
from fdai_service_contracts.cloud_knowledge_release import (
    KnowledgeManifest,
    KnowledgeReleaseBinding,
    KnowledgeStructuredReleaseManifest,
    KnowledgeTextReleaseManifest,
    normalized_document,
    parse_knowledge_manifest,
)
from fdai_service_contracts.cloud_knowledge_structure import CloudStructuredDocument, excerpt_digest

from fdai_ingestion_api_service.cloud_knowledge.projection import project_source, project_status
from fdai_ingestion_api_service.cloud_knowledge.scheduler import CloudKnowledgeScheduler
from fdai_ingestion_api_service.cloud_knowledge.store import PostgresCloudKnowledgeStore
from fdai_ingestion_api_service.ingestion import CreateUploadRequest, DocumentIngestionService


def _identity(value: str) -> UUID:
    return UUID(hex=content_digest(value.encode())[:32], version=4)


class CloudKnowledgeService:
    """Collection, package inspection, and intake never approve or directly activate knowledge."""

    def __init__(
        self,
        *,
        registry: SourceRegistryRevision,
        trust: KnowledgeTrustPolicy,
        store: PostgresCloudKnowledgeStore,
        scheduler: CloudKnowledgeScheduler,
        ingestion: DocumentIngestionService,
        clock: Callable[[], datetime],
        reader_groups: tuple[str, ...],
        retention_policy: str,
        current_policy: Callable[[], tuple[SourceRegistryRevision, KnowledgeTrustPolicy]]
        | None = None,
        structured: bool = False,
    ) -> None:
        self.registry = registry
        self.trust = trust
        self._store = store
        self._scheduler = scheduler
        self._ingestion = ingestion
        self._clock = clock
        self._groups = reader_groups
        self._retention_policy = retention_policy
        self._current_policy = current_policy or (lambda: (registry, trust))
        self._structured = structured

    def _policies(self) -> tuple[SourceRegistryRevision, KnowledgeTrustPolicy]:
        registry, trust = self._current_policy()
        if registry.digest != self.registry.digest:
            raise ValueError("source registry changed; reload the approved source binding")
        if self._clock() >= registry.valid_until:
            raise ValueError("source registry approval has expired")
        return registry, trust

    def authorize_content(self, version: DocumentVersion) -> None:
        """Keep metadata inspectable while refusing revoked or expired document bodies."""
        if version.cloud_knowledge is None:
            return
        try:
            registry, trust = self._policies()
            validate_admitted_binding(
                version.cloud_knowledge, registry=registry, trust=trust, now=self._clock()
            )
        except ValueError:
            raise DocumentAccessDeniedError("cloud knowledge content is unavailable") from None

    async def source_projection(
        self, version: DocumentVersion, serialized: str
    ) -> dict[str, object]:
        """Return the active source's check overlay without changing the historical binding."""
        self.authorize_content(version)
        return await project_source(
            version,
            serialized,
            read_checkpoint=self._store.get,
            clock=lambda: self._clock(),
        )

    async def status(self, *, actor_id: str, actor_groups: frozenset[str]) -> dict[str, object]:
        """Project configured and observed states; never substitute a candidate for active data."""
        return await project_status(
            actor_id=actor_id,
            actor_groups=actor_groups,
            registry=self.registry,
            list_versions=self._ingestion.list_versions,
            read_checkpoint=self._store.get,
            check_policy=self._policies,
            content_admitted=self._content_admitted,
            clock=lambda: self._clock(),
            document_id_for=lambda collection: _identity(f"cloud-knowledge:{collection}"),
        )

    def _content_admitted(self, version: DocumentVersion) -> bool:
        """Keep management records readable while projecting expired/revoked bodies unavailable."""
        try:
            self.authorize_content(version)
        except (DocumentAccessDeniedError, OSError):
            return False
        return True

    async def refresh(self) -> dict[str, int | str]:
        """Request one authorized bounded sweep; source policies still determine what is due."""
        self._policies()
        return await self._scheduler.tick()

    async def proposal(
        self, collection_id: str
    ) -> KnowledgeTextReleaseManifest | KnowledgeStructuredReleaseManifest:
        """Build complete normalized-only review material; collector originals stay local."""
        now = self._clock()
        self._policies()
        if now >= self.registry.valid_until:
            raise ValueError("source registry approval has expired")
        sources = [item for item in self.registry.sources if item.collection_id == collection_id]
        if not sources:
            raise ValueError("collection is not registered")
        documents = []
        structured_documents: list[CloudStructuredDocument] = []
        for source in sources:
            state = (await self._store.get(self.registry.digest, source.source_id)).state
            if (
                state.document is None
                or state.last_attempt is None
                or state.last_attempt.outcome not in {"fetched", "unchanged", "changed"}
            ):
                raise ValueError("complete successful source coverage is required")
            if not source.storage_allowed or not source.internal_transfer_allowed:
                raise ValueError("document review export requires approved transfer rights")
            documents.append(normalized_document(state.document))
            if self._structured:
                from fdai_ingestion_api_service.cloud_knowledge.structured_normalization import (
                    reprocess_document,
                )

                structured_documents.append(
                    state.structured_document or reprocess_document(state.document, now=now)
                )
        sequence = await self._store.next_sequence(collection_id)
        if self._structured:
            return KnowledgeStructuredReleaseManifest(
                release_id=f"{collection_id}-{sequence}",
                sequence=sequence,
                collection_id=collection_id,
                registry_digest=self.registry.digest,
                package_created_at=now,
                expires_at=min(self.registry.valid_until, now + timedelta(days=30)),
                documents=tuple(structured_documents),
                excerpt_digests=tuple(
                    excerpt_digest(document) for document in structured_documents
                ),
            )
        return KnowledgeTextReleaseManifest(
            release_id=f"{collection_id}-{sequence}",
            sequence=sequence,
            collection_id=collection_id,
            registry_digest=self.registry.digest,
            package_created_at=now,
            expires_at=min(self.registry.valid_until, now + timedelta(days=30)),
            documents=tuple(documents),
        )

    async def stage_collected(
        self, *, collection_id: str, actor_id: str, actor_groups: frozenset[str]
    ) -> dict[str, object]:
        """Stage collector observations through the same scan, human review, and index gates."""
        manifest = await self.proposal(collection_id)
        binding = KnowledgeReleaseBinding(
            release_id=manifest.release_id,
            sequence=manifest.sequence,
            manifest_digest=manifest.digest,
            registry_digest=self.registry.digest,
            package_created_at=manifest.package_created_at,
            imported_at=self._clock(),
            admission_expires_at=manifest.expires_at,
            verified_key_id="connected-collector",
            intake_origin="collector",
            sources=tuple(item.evidence for item in manifest.documents),
            processing_digests=(
                tuple(item.processing_digest for item in manifest.documents)
                if isinstance(manifest, KnowledgeStructuredReleaseManifest)
                else ()
            ),
        )
        return await self._ingest(manifest, binding, actor_id=actor_id, actor_groups=actor_groups)

    def inspect(self, content: bytes) -> dict[str, object]:
        """Verify sealed bytes without importing, indexing, or granting approval."""
        registry, trust = self._policies()
        verified = verify_package(content, registry=registry, trust=trust, now=self._clock())
        return {
            "status": "verified_candidate",
            "approval_required": True,
            "release": verified.binding.model_dump(mode="json"),
            "document_count": len(verified.manifest.documents),
        }

    async def import_package(
        self, content: bytes, *, actor_id: str, actor_groups: frozenset[str]
    ) -> dict[str, object]:
        """Verify again at import; inspection output supplied by a client is never trusted."""
        registry, trust = self._policies()
        verified = verify_package(content, registry=registry, trust=trust, now=self._clock())
        return await self._ingest(
            verified.manifest, verified.binding, actor_id=actor_id, actor_groups=actor_groups
        )

    async def rollback(
        self, *, collection_id: str, version_id: UUID, actor_id: str, actor_groups: frozenset[str]
    ) -> dict[str, object]:
        """Create a higher-sequence review request from still-admissible retained source bytes."""
        if "role:Owner" not in actor_groups:
            raise DocumentAccessDeniedError("knowledge rollback requires owner access")
        registry, trust = self._policies()
        version, content = await self._ingestion.read_cloud_reference_revision(
            actor_id=actor_id,
            actor_groups=actor_groups,
            document_id=_identity(f"cloud-knowledge:{collection_id}"),
            version_id=version_id,
        )
        prior = version.cloud_knowledge
        if prior is None:
            raise ValueError("knowledge rollback source binding is missing")
        validate_admitted_binding(prior, registry=registry, trust=trust, now=self._clock())
        original = parse_knowledge_manifest(content)
        if original.digest != prior.manifest_digest or canonical_bytes(original) != content:
            raise ValueError("knowledge rollback manifest identity changed")
        current_versions = await self._ingestion.list_versions(
            actor_id=actor_id,
            actor_groups=actor_groups,
            document_id=version.document_id,
        )
        withdrawn = {
            source
            for candidate in current_versions
            if candidate.cloud_knowledge is not None
            for source in candidate.cloud_knowledge.withdrawn_source_ids
        }
        if withdrawn.intersection(source.source_id for source in prior.sources):
            raise ValueError("knowledge rollback cannot resurrect a withdrawn source")
        sequence = await self._store.next_sequence(collection_id)
        manifest: KnowledgeTextReleaseManifest | KnowledgeStructuredReleaseManifest
        if isinstance(original, KnowledgeStructuredReleaseManifest):
            manifest = KnowledgeStructuredReleaseManifest.model_validate(
                original.model_dump()
                | {
                    "release_id": f"{collection_id}-rollback-{sequence}",
                    "sequence": sequence,
                    "package_created_at": self._clock(),
                    "expires_at": prior.admission_expires_at,
                }
            )
        else:
            manifest = KnowledgeTextReleaseManifest.model_validate(
                original.model_dump(exclude={"schema_version", "reader_version", "documents"})
                | {
                    "release_id": f"{collection_id}-rollback-{sequence}",
                    "sequence": sequence,
                    "package_created_at": self._clock(),
                    "expires_at": prior.admission_expires_at,
                    "documents": tuple(
                        normalized_document(document) for document in original.documents
                    ),
                }
            )
        binding = KnowledgeReleaseBinding(
            release_id=manifest.release_id,
            sequence=sequence,
            manifest_digest=manifest.digest,
            registry_digest=manifest.registry_digest,
            package_created_at=manifest.package_created_at,
            imported_at=self._clock(),
            admission_expires_at=prior.admission_expires_at,
            verified_key_id=prior.verified_key_id,
            intake_origin="rollback",
            rollback_of=prior.release_id,
            rollback_source_digest=prior.manifest_digest,
            sources=prior.sources,
            processing_digests=prior.processing_digests,
            withdrawn_source_ids=original.withdrawn_source_ids,
        )
        return await self._ingest(manifest, binding, actor_id=actor_id, actor_groups=actor_groups)

    async def _ingest(
        self,
        manifest: KnowledgeManifest,
        binding: KnowledgeReleaseBinding,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
    ) -> dict[str, object]:
        if not actor_groups.intersection({"role:Contributor", "role:Approver", "role:Owner"}):
            raise DocumentAccessDeniedError("cloud knowledge intake requires contributor access")
        content = canonical_bytes(manifest)
        document_id = _identity(f"cloud-knowledge:{manifest.collection_id}")
        version_id = _identity(f"cloud-version:{manifest.digest}")
        upload_id = _identity(f"cloud-upload:{manifest.digest}")
        versions = await self._ingestion.list_versions(
            actor_id=actor_id,
            actor_groups=actor_groups,
            document_id=document_id,
        )
        active = next(
            (item for item in versions if item.document_id == document_id and item.active), None
        )
        await self._ingestion.authorize_cloud_reference_intake(
            actor_id=actor_id,
            actor_groups=actor_groups,
            collection_id=manifest.collection_id,
            previous=active,
        )
        record = await self._store.reserve_release(
            collection_id=manifest.collection_id,
            sequence=manifest.sequence,
            digest=manifest.digest,
            upload_id=upload_id,
            payload=json.dumps(
                {
                    "binding": binding.model_dump(mode="json"),
                    "actor_id": actor_id,
                    "supersedes_version_id": str(active.version_id) if active else None,
                }
            ),
        )
        if record.get("actor_id") != actor_id:
            raise DocumentAccessDeniedError("knowledge intake belongs to a different requester")
        binding = KnowledgeReleaseBinding.model_validate(record["binding"])
        if self._clock() >= binding.admission_expires_at:
            raise ValueError("knowledge intake authorization has expired")
        try:
            session = await self._ingestion.get_upload(
                actor_id=actor_id, actor_groups=actor_groups, upload_id=upload_id
            )
        except DocumentNotFoundError:
            previous = record.get("supersedes_version_id")
            request = CreateUploadRequest(
                source_name=f"{manifest.release_id}.json",
                collection_id=manifest.collection_id,
                media_type_hint="application/json",
                expected_size=len(content),
                expected_sha256=manifest.digest,
                storage_mode=SourceStorageMode.MANAGED_COPY,
                purposes=(DocumentPurpose.KNOWLEDGE_BASE, DocumentPurpose.CLOUD_REFERENCE),
                access_descriptor_ref=f"collection:{manifest.collection_id}",
                reader_groups=self._groups,
                retention_policy_version=self._retention_policy,
                document_id=document_id,
                version_id=version_id,
                upload_id=upload_id,
                connector_idempotency_key=f"cloud-reference:{manifest.digest}",
                supersedes_version_id=UUID(str(previous)) if previous else None,
                cloud_knowledge=binding,
            )
            session, _grant = await self._ingestion.create_upload(
                actor_id=actor_id,
                actor_groups=actor_groups,
                request=request,
            )
        if session.state.value == "uploading":

            async def chunks() -> AsyncIterator[bytes]:
                yield content

            await self._ingestion.put_streaming_content(
                actor_id=actor_id,
                actor_groups=actor_groups,
                upload_id=upload_id,
                chunks=chunks(),
            )
            session = await self._ingestion.complete_upload(
                actor_id=actor_id,
                actor_groups=actor_groups,
                upload_id=upload_id,
            )
        return {
            "session": session.model_dump(mode="json"),
            "approval_required": True,
            "status": "ingestion_requested",
            "release": binding.model_dump(mode="json"),
        }
