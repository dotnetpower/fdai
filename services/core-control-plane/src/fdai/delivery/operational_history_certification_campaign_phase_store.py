"""Persist one sanitized OI-16 campaign phase artifact inside the synthetic scope.

The before-restart phase writes its sanitized manifest as a content-addressed
artifact through the existing principal-scoped Blob adapter and indexes it in the
synthetic operational-history archive tables. The after-restart phase reads that
artifact back so an externally executed Azure PostgreSQL restart can sit between
the two runs. Scope, purpose, storage reference, byte count, and content digest
are all re-verified on read, so a mismatch fails closed instead of continuing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from fdai.delivery.operational_history_archive import OperationalArchiveArtifact
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_PURPOSE,
    CampaignPhase,
    SyntheticScope,
    assert_sanitized,
    evidence_digest,
)

MAX_PHASE_BYTES = 1_048_576
_PHASE_DIGEST_DOMAIN = "oi16-campaign-phase"
_STORAGE_ROOT = "operational-history/oi16-certification-campaign"
_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign.phase_store")


class PhaseArtifactStore(Protocol):
    """Bounded content-addressed byte store for one campaign phase artifact."""

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool: ...

    async def get(self, storage_ref: str) -> bytes | None: ...


class PhaseMetadataStore(Protocol):
    """Scope-bound and purpose-bound artifact index for campaign phase artifacts."""

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool: ...

    async def get_archive_artifact(
        self, manifest_digest: str
    ) -> OperationalArchiveArtifact | None: ...


def phase_key_digest(campaign_id: str, phase: CampaignPhase) -> str:
    """Return the deterministic index key for one campaign phase artifact."""

    material = "|".join((_PHASE_DIGEST_DOMAIN, campaign_id, phase.value))
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


def phase_storage_ref(campaign_id: str, phase: CampaignPhase) -> str:
    """Return the deterministic synthetic storage reference for a phase artifact."""

    return f"{_STORAGE_ROOT}/{campaign_id}/{phase.value}.json"


class CampaignPhaseStore:
    """Round-trip sanitized phase manifests through the synthetic archive scope."""

    def __init__(
        self,
        *,
        artifacts: PhaseArtifactStore,
        metadata: PhaseMetadataStore,
        scope: SyntheticScope,
    ) -> None:
        self._artifacts = artifacts
        self._metadata = metadata
        self._scope = scope

    async def put(
        self,
        manifest: Mapping[str, object],
        *,
        campaign_id: str,
        phase: CampaignPhase,
        now: datetime,
    ) -> OperationalArchiveArtifact:
        """Store one sanitized phase manifest and index it in the synthetic scope."""

        assert_sanitized(manifest)
        encoded = _encode(manifest)
        if not 0 < len(encoded) <= MAX_PHASE_BYTES:
            raise ValueError("campaign phase artifact size is outside its bound")
        content_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        artifact = self._artifact(
            content_digest=content_digest,
            byte_count=len(encoded),
            campaign_id=campaign_id,
            phase=phase,
            created_at=now.astimezone(UTC),
        )
        await self._artifacts.put(artifact.storage_ref, encoded, digest=content_digest[7:])
        await self._metadata.put_archive_artifact(artifact)
        _LOGGER.info("campaign phase artifact stored phase=%s", phase.value)
        return artifact

    async def get(self, *, campaign_id: str, phase: CampaignPhase) -> dict[str, object] | None:
        """Return the stored phase manifest, or ``None`` when it was never written."""

        key = phase_key_digest(campaign_id, phase)
        artifact = await self._metadata.get_archive_artifact(key)
        if artifact is None:
            return None
        self._assert_bound(artifact, campaign_id=campaign_id, phase=phase)
        content = await self._artifacts.get(artifact.storage_ref)
        if content is None:
            raise LookupError("campaign phase artifact index has no stored content")
        if len(content) != artifact.byte_count:
            raise ValueError("campaign phase artifact byte count does not match its index")
        if "sha256:" + hashlib.sha256(content).hexdigest() != artifact.artifact_digest:
            raise ValueError("campaign phase artifact content does not match its digest")
        manifest = json.loads(content.decode())
        if not isinstance(manifest, dict):
            raise ValueError("campaign phase artifact MUST decode to a manifest mapping")
        assert_sanitized(manifest)
        return manifest

    def _assert_bound(
        self,
        artifact: OperationalArchiveArtifact,
        *,
        campaign_id: str,
        phase: CampaignPhase,
    ) -> None:
        if artifact.scope_refs != (self._scope.scope_ref,):
            raise PermissionError("campaign phase artifact is bound to another scope")
        if artifact.allowed_purposes != (CAMPAIGN_PURPOSE,):
            raise PermissionError("campaign phase artifact is bound to another purpose")
        if artifact.storage_ref != phase_storage_ref(campaign_id, phase):
            raise ValueError("campaign phase artifact storage reference is unexpected")

    def _artifact(
        self,
        *,
        content_digest: str,
        byte_count: int,
        campaign_id: str,
        phase: CampaignPhase,
        created_at: datetime,
    ) -> OperationalArchiveArtifact:
        body: dict[str, object] = {
            "artifact_digest": content_digest,
            "storage_ref": phase_storage_ref(campaign_id, phase),
            "manifest_digest": phase_key_digest(campaign_id, phase),
            "scope_refs": [self._scope.scope_ref],
            "allowed_purposes": [CAMPAIGN_PURPOSE],
            "byte_count": byte_count,
            "created_at": created_at.isoformat(),
        }
        return OperationalArchiveArtifact(
            artifact_digest=content_digest,
            storage_ref=str(body["storage_ref"]),
            manifest_digest=str(body["manifest_digest"]),
            scope_refs=(self._scope.scope_ref,),
            allowed_purposes=(CAMPAIGN_PURPOSE,),
            byte_count=byte_count,
            created_at=created_at,
            digest=evidence_digest(body),
        )


def _encode(manifest: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(manifest),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


__all__ = [
    "MAX_PHASE_BYTES",
    "CampaignPhaseStore",
    "PhaseArtifactStore",
    "PhaseMetadataStore",
    "phase_key_digest",
    "phase_storage_ref",
]
