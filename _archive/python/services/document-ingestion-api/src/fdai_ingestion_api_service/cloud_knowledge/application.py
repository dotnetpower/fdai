"""Bind explicit requester applications to previously reviewed, persisted authority."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fdai_service_contracts.cloud_knowledge_application import (
    CloudApplicationRequest,
    cloud_index_input_digest,
    validate_application,
)
from fdai_service_contracts.cloud_knowledge_release import (
    KnowledgeManifest,
    KnowledgeReleaseBinding,
)

from fdai_ingestion_api_service.cloud_knowledge.application_store import (
    PostgresCloudApplicationStore,
)


async def bind_application(
    *,
    store: PostgresCloudApplicationStore,
    policy_digest: str,
    binding: KnowledgeReleaseBinding,
    manifest: KnowledgeManifest,
    requester_id: str,
    reader_groups: tuple[str, ...],
    document_id: UUID,
    version_id: UUID,
    upload_id: UUID,
    previous_id: UUID | None,
    now: datetime,
    size_bytes: int,
) -> KnowledgeReleaseBinding:
    authority = await store.get(policy_digest)
    policy = authority.policy
    authority.require_current(requester_id, now)
    if manifest.schema_version == "fdai.cloud-knowledge.v1":
        raise ValueError("requester application requires normalized-only v2 or structured v3")
    if (
        manifest.schema_version not in policy.manifest_versions
        or any(d.normalizer_version not in policy.normalizer_versions for d in manifest.documents)
        or size_bytes > policy.max_bytes
        or binding.withdrawn_source_ids
        or binding.intake_origin == "rollback"
    ):
        raise ValueError("application content or processing is outside prior policy")
    request = CloudApplicationRequest(
        nonce=uuid4(),
        policy_digest=policy_digest,
        requester_id=requester_id,
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        manifest_digest=manifest.digest,
        manifest_version=manifest.schema_version,
        normalizer_versions=tuple(d.normalizer_version for d in manifest.documents),
        index_input_digest=cloud_index_input_digest(binding),
        collection_id=manifest.collection_id,
        expected_active_version_id=previous_id,
        idempotency_key=f"cloud-apply:{manifest.digest}",
        requested_at=now,
        expires_at=min(
            policy.valid_until,
            binding.admission_expires_at,
            now + timedelta(seconds=policy.request_ttl_seconds),
        ),
    )
    validate_application(
        authority,
        request,
        now=now,
        requester_id=requester_id,
        manifest_digest=manifest.digest,
        index_input_digest=cloud_index_input_digest(binding),
        collection_id=manifest.collection_id,
        registry_digest=binding.registry_digest,
        source_ids=tuple(s.source_id for s in binding.sources),
        reader_groups=reader_groups,
    )
    persisted = await store.reserve(request)
    if not persisted.requested_at <= now < persisted.expires_at:
        raise ValueError("application retry cannot renew an expired request")
    return binding.model_copy(update={"application": persisted})
