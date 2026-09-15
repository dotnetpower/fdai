"""Read-only cloud-reference projections over authorized versions and source checkpoints.

The service facade owns authorization, policy, admission, and deterministic document identity.
Injected read callbacks expose no collection, intake, activation, or persistence-write operations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fdai_service_contracts import DocumentVersion
from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    Freshness,
    SourceRegistryRevision,
)
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy
from fdai_service_contracts.cloud_knowledge_updates import source_update_pending

if TYPE_CHECKING:
    from fdai_ingestion_api_service.cloud_knowledge.store import SourceCheckpoint


class _ListVersions(Protocol):
    """Read document versions through the ingestion service's actor-scoped authorization."""

    async def __call__(
        self, *, actor_id: str, actor_groups: frozenset[str], document_id: UUID
    ) -> tuple[DocumentVersion, ...]: ...


async def project_source(
    version: DocumentVersion,
    serialized: str,
    *,
    read_checkpoint: Callable[[str, str], Awaitable[SourceCheckpoint]],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Overlay a source check after the facade has authorized the version's content.

    Identity mismatches raise ValueError. Only a newer same-content check can replace the
    projected receipt; the historical binding is never mutated and read failures propagate.
    """
    binding = version.cloud_knowledge
    if binding is None:
        raise ValueError("cloud citation has no release binding")
    indexed = CloudSourceEvidence.model_validate_json(serialized)
    source = next((item for item in binding.sources if item.source_id == indexed.source_id), None)
    if source is None or source.source_sha256 != indexed.source_sha256:
        raise ValueError("cloud citation source identity changed")
    state = (await read_checkpoint(binding.registry_digest, source.source_id)).state
    pending = bool(
        state.document
        and source_update_pending(
            binding, source, state.document.evidence, state.structured_document
        )
    )
    receipt = state.document.evidence.check if state.document else None
    if (
        not pending
        and receipt
        and receipt.content_sha256 == source.source_sha256
        and source.check.checked_at < receipt.checked_at <= clock()
    ):
        source = CloudSourceEvidence.model_validate(
            source.model_dump()
            | {
                "check": receipt.model_dump(),
            }
        )
    return {
        "source_id": source.source_id,
        "collected_at": source.collected_at.isoformat(),
        "checked_at": source.check.checked_at.isoformat(),
        "update_pending": pending,
        "freshness": source.freshness(clock()).value,
        "source_url": source.source_url,
        "applicability": source.applicability.model_dump(mode="json"),
        "retrieval_mode": "lexical",
        "live_observation": False,
    }


async def project_status(
    *,
    actor_id: str,
    actor_groups: frozenset[str],
    registry: SourceRegistryRevision,
    list_versions: _ListVersions,
    read_checkpoint: Callable[[str, str], Awaitable[SourceCheckpoint]],
    check_policy: Callable[[], tuple[SourceRegistryRevision, KnowledgeTrustPolicy]],
    content_admitted: Callable[[DocumentVersion], bool],
    clock: Callable[[], datetime],
    document_id_for: Callable[[str], UUID],
) -> dict[str, object]:
    """Project configured and admitted states without substituting candidates for active data.

    Callers supply authorized version reads, current policy/admission gates, and the same
    collection-to-document identity used for intake. Policy failure leaves management metadata
    inspectable while each version retains its own content-admission check.
    """
    rows: list[dict[str, object]] = []
    collections: list[dict[str, object]] = []
    now = clock()
    try:
        check_policy()
        policy_current = True
    except (OSError, ValueError):
        policy_current = False
    for collection in sorted({source.collection_id for source in registry.sources}):
        versions = await list_versions(
            actor_id=actor_id,
            actor_groups=actor_groups,
            document_id=document_id_for(collection),
        )
        relevant = [version for version in versions if version.cloud_knowledge is not None]
        collections.append(
            {
                "collection_id": collection,
                "versions": [
                    {
                        "document_id": str(version.document_id),
                        "version_id": str(version.version_id),
                        "state": version.state.value,
                        "active": version.active,
                        "available": version.available and content_admitted(version),
                        "updated_at": version.updated_at.isoformat(),
                        "release": version.cloud_knowledge.model_dump(mode="json")
                        if version.cloud_knowledge
                        else None,
                    }
                    for version in relevant
                ],
            }
        )
        active = next(
            (
                version
                for version in relevant
                if version.active and version.available and content_admitted(version)
            ),
            None,
        )
        for source in (item for item in registry.sources if item.collection_id == collection):
            checkpoint = await read_checkpoint(registry.digest, source.source_id)
            cached = checkpoint.state.document
            admitted = (
                next(
                    (
                        item
                        for item in active.cloud_knowledge.sources
                        if item.source_id == source.source_id
                    ),
                    None,
                )
                if (active and active.cloud_knowledge)
                else None
            )
            if (
                admitted is not None
                and cached is not None
                and (
                    active is not None
                    and active.cloud_knowledge is not None
                    and not source_update_pending(
                        active.cloud_knowledge,
                        admitted,
                        cached.evidence,
                        checkpoint.state.structured_document,
                    )
                    and admitted.check.checked_at < cached.evidence.check.checked_at <= now
                )
            ):
                admitted = CloudSourceEvidence.model_validate(
                    admitted.model_dump()
                    | {
                        "check": cached.evidence.check.model_dump(),
                    }
                )
            rows.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "collection_id": collection,
                    "mode": source.mode,
                    "enabled": source.enabled,
                    "check_interval_seconds": source.policy.check_interval_seconds,
                    "max_unverified_seconds": source.policy.max_unverified_seconds,
                    "collected_at": admitted.collected_at.isoformat() if admitted else None,
                    "checked_at": admitted.check.checked_at.isoformat() if admitted else None,
                    "freshness": admitted.freshness(now).value
                    if admitted
                    else Freshness.UNKNOWN.value,
                    "next_due_at": (
                        admitted.check.checked_at
                        + timedelta(seconds=source.policy.check_interval_seconds)
                    ).isoformat()
                    if admitted
                    else None,
                    "last_attempt": checkpoint.state.last_attempt.model_dump(mode="json")
                    if checkpoint.state.last_attempt
                    else None,
                    "update_pending": bool(
                        cached
                        and (
                            admitted is None
                            or active is None
                            or active.cloud_knowledge is None
                            or source_update_pending(
                                active.cloud_knowledge,
                                admitted,
                                cached.evidence,
                                checkpoint.state.structured_document,
                            )
                        )
                    ),
                    "consecutive_failures": checkpoint.state.consecutive_failures,
                }
            )
    return {
        "available": True,
        "policy_current": policy_current,
        "reason": None if policy_current else "source_policy_unavailable_or_expired",
        "registry_revision": registry.revision,
        "registry_valid_until": registry.valid_until.isoformat(),
        "sources": rows,
        "collections": collections,
        "automatic_activation": False,
        "approval_required": True,
    }
