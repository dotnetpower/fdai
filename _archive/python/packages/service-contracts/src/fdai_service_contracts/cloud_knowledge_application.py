"""Prior human authority for exact reference-content applications, never self-approval."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from fdai_service_contracts.cloud_knowledge import (
    Digest,
    Identifier,
    KnowledgeContract,
    canonical_bytes,
    content_digest,
)

if TYPE_CHECKING:
    from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding
    from fdai_service_contracts.document import DocumentVersion


class CloudApplicationUnavailableError(ValueError):
    """Current prior authority cannot support visibility; contain the pending generation."""


def _principal_key(value: str) -> str:
    return value.strip().casefold()


class CloudApplicationPolicy(KnowledgeContract):
    """Closed policy proposal; the server records its author and independent reviewer separately."""

    policy_id: Identifier
    revision: Annotated[StrictInt, Field(ge=1)]
    collection_id: Identifier
    registry_digest: Digest
    requester_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    reader_groups: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    source_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=256)]
    normalizer_versions: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    manifest_versions: tuple[Literal["fdai.cloud-knowledge.v2", "fdai.cloud-knowledge.v3"], ...]
    max_bytes: Annotated[StrictInt, Field(ge=1, le=16 * 1024 * 1024)]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    request_ttl_seconds: Annotated[StrictInt, Field(ge=1, le=3600)] = 900
    stop_condition: Annotated[str, Field(min_length=1, max_length=512)]
    tested_rollback_ref: Annotated[str, Field(min_length=1, max_length=512)]
    successful_dry_run_ref: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if self.valid_from >= self.valid_until or not self.manifest_versions:
            raise ValueError("application policy requires a bounded interval and formats")
        for values in (
            self.requester_ids,
            self.reader_groups,
            self.source_ids,
            self.normalizer_versions,
            self.manifest_versions,
        ):
            if len(set(values)) != len(values) or any(not v.strip() or v == "*" for v in values):
                raise ValueError("application policy identities must be explicit and unique")
        for principals in (self.requester_ids, self.reader_groups):
            if len({_principal_key(value) for value in principals}) != len(principals):
                raise ValueError("application policy principals must be canonically unique")
        return self

    @property
    def digest(self) -> str:
        return content_digest(canonical_bytes(self))


class CloudPolicyAuthority(KnowledgeContract):
    policy: CloudApplicationPolicy
    author_id: Annotated[str, Field(min_length=1, max_length=256)]
    approved_by: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    approved_at: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None

    def require_independent_reviewer(self, reviewer: str, now: datetime) -> None:
        reviewer_key = _principal_key(reviewer)
        requester_keys = {_principal_key(value) for value in self.policy.requester_ids}
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or not reviewer_key
            or reviewer_key == _principal_key(self.author_id)
            or reviewer_key in requester_keys
            or self.approved_by is not None
            or self.revoked_at is not None
            or now >= self.policy.valid_until
        ):
            raise ValueError("policy requires a new independent human review")

    def require_current(self, requester: str, now: datetime) -> None:
        """A reviewed policy, not its signature or source registry, establishes prior authority."""
        approved_by = _principal_key(self.approved_by or "")
        requester_keys = {_principal_key(value) for value in self.policy.requester_ids}
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or not approved_by
            or approved_by == _principal_key(self.author_id)
            or approved_by in requester_keys
            or _principal_key(requester) not in requester_keys
            or self.approved_at is None
            or not self.approved_at <= now
            or self.revoked_at is not None
            or not self.policy.valid_from <= now < self.policy.valid_until
        ):
            raise ValueError("independent current application authority is unavailable")


class CloudApplicationRequest(KnowledgeContract):
    """Server-issued nonce and immutable request-time bindings survive delivery and restart."""

    nonce: UUID
    policy_digest: Digest
    requester_id: str
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    manifest_digest: Digest
    manifest_version: Literal["fdai.cloud-knowledge.v2", "fdai.cloud-knowledge.v3"]
    normalizer_versions: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    index_input_digest: Digest
    collection_id: Identifier
    expected_active_version_id: UUID | None
    idempotency_key: Identifier
    requested_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.requested_at >= self.expires_at:
            raise ValueError("application request requires a positive validity interval")
        return self


class CloudApplicationAuthorization(KnowledgeContract):
    request: CloudApplicationRequest
    approved_by: str


class CloudApplicationAuthorizationSource(Protocol):
    async def authorize(
        self, *, document_id: str, upload_id: str, requester_id: str
    ) -> CloudApplicationAuthorization | None:
        """Read independent persisted authority; None means an actual manual-lane version."""
        ...


def validate_application(
    authority: CloudPolicyAuthority,
    request: CloudApplicationRequest,
    *,
    now: datetime,
    requester_id: str,
    manifest_digest: str,
    index_input_digest: str,
    collection_id: str,
    registry_digest: str,
    source_ids: tuple[str, ...],
    reader_groups: tuple[str, ...],
) -> None:
    """Recheck immutable authority and scope without creating, renewing, or widening them."""
    authority.require_current(requester_id, now)
    policy = authority.policy
    if (
        request.policy_digest != policy.digest
        or request.requester_id != requester_id
        or request.manifest_digest != manifest_digest
        or request.index_input_digest != index_input_digest
        or request.collection_id != collection_id
        or policy.collection_id != collection_id
        or policy.registry_digest != registry_digest
        or set(policy.source_ids) != set(source_ids)
        or set(policy.reader_groups) != set(reader_groups)
        or not request.requested_at <= now < request.expires_at <= policy.valid_until
        or request.expires_at.timestamp() - request.requested_at.timestamp()
        > policy.request_ttl_seconds
        or authority.approved_at is None
        or authority.approved_at > request.requested_at
    ):
        raise ValueError("application binding changed or expired")


def cloud_index_input_digest(binding: KnowledgeReleaseBinding) -> str:
    """Pin all immutable provenance and processing inputs independently of the request nonce."""
    data = binding.model_dump(
        mode="json",
        include={"manifest_digest", "registry_digest", "sources", "processing_digests"},
    )
    return content_digest(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def validate_application_version(
    authority: CloudPolicyAuthority,
    persisted: CloudApplicationRequest,
    version: DocumentVersion,
    now: datetime,
) -> None:
    """Validate a persisted worker/agent version, not an event's claimed approval or requester."""
    binding = version.cloud_knowledge
    if (
        binding is None
        or binding.application != persisted
        or persisted.upload_id != version.upload_id
        or persisted.document_id != version.document_id
        or persisted.version_id != version.version_id
        or persisted.expected_active_version_id != version.supersedes_version_id
        or version.sensitivity_label
        or version.classification not in {"unclassified", "public"}
        or {p.value for p in version.purposes} != {"knowledge_base", "cloud_reference"}
        or version.size_bytes > authority.policy.max_bytes
        or persisted.manifest_version not in authority.policy.manifest_versions
        or not set(persisted.normalizer_versions).issubset(authority.policy.normalizer_versions)
    ):
        raise ValueError("application version is not eligible ordinary reference content")
    validate_application(
        authority,
        persisted,
        now=now,
        requester_id=version.uploader_id,
        manifest_digest=version.source_sha256,
        index_input_digest=cloud_index_input_digest(binding),
        collection_id=version.access.collection_id,
        registry_digest=binding.registry_digest,
        source_ids=tuple(s.source_id for s in binding.sources),
        reader_groups=version.access.reader_groups,
    )
