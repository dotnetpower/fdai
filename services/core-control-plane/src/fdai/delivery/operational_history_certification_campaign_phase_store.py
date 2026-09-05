"""Persist one sanitized OI-16 campaign phase artifact inside the synthetic scope.

The before-restart phase writes its sanitized manifest as a content-addressed
artifact through the existing principal-scoped Blob adapter. The after-restart
phase reads that deterministic path back so an externally executed Azure PostgreSQL
restart can sit between the two runs. Scope, purpose, campaign, phase, and content
digest are re-verified on read, so a mismatch fails closed instead of continuing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveSourcePartition,
    ArchiveVerificationReceipt,
    build_archive_manifest,
    verify_archive_manifest,
)
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


class PhaseManifestStore(Protocol):
    """Append-only archive manifest store for campaign phase content."""

    async def put_manifest(self, manifest: ArchiveManifest) -> bool: ...

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool: ...


class PhaseMetadataStore(Protocol):
    """Out-of-band artifact index for campaign phase content."""

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool: ...

    async def get_archive_artifact_by_storage_ref(
        self, storage_ref: str
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
        manifests: PhaseManifestStore,
        metadata: PhaseMetadataStore,
        scope: SyntheticScope,
    ) -> None:
        self._artifacts = artifacts
        self._manifests = manifests
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
        """Store one sanitized phase manifest in its deterministic synthetic Blob path."""

        assert_sanitized(manifest)
        envelope: dict[str, object] = {
            "campaign_id": campaign_id,
            "phase": phase.value,
            "purpose": CAMPAIGN_PURPOSE,
            "scope_digest": self._scope.digest,
            "manifest": dict(manifest),
        }
        encoded = _encode(envelope)
        if not 0 < len(encoded) <= MAX_PHASE_BYTES:
            raise ValueError("campaign phase artifact size is outside its bound")
        content_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        created_at = now.astimezone(UTC)
        archive_manifest = self._manifest(
            manifest,
            content_digest=content_digest,
            campaign_id=campaign_id,
            phase=phase,
            created_at=created_at,
        )
        artifact = self._artifact(
            content_digest=content_digest,
            byte_count=len(encoded),
            campaign_id=campaign_id,
            phase=phase,
            manifest_digest=archive_manifest.digest,
            created_at=created_at,
        )
        await self._artifacts.put(artifact.storage_ref, encoded, digest=content_digest[7:])
        observed = await self._artifacts.get(artifact.storage_ref)
        if observed != encoded:
            raise ValueError("campaign phase Blob readback does not match its write")
        verification = verify_archive_manifest(
            archive_manifest,
            observed_archive_content_digest=content_digest,
            observed_source_partition_digests=(content_digest,),
            observed_source_schema_versions=("oi16-campaign-phase/1.0.0",),
            observed_ontology_release_digests=archive_manifest.ontology_release_digests,
            verified_at=created_at,
        )
        if not verification.verified:
            raise ValueError("campaign phase archive manifest verification failed")
        await self._manifests.put_manifest(archive_manifest)
        await self._manifests.append_verification(verification)
        await self._metadata.put_archive_artifact(artifact)
        _LOGGER.info("campaign phase artifact stored phase=%s", phase.value)
        return artifact

    async def get(self, *, campaign_id: str, phase: CampaignPhase) -> dict[str, object] | None:
        """Return the stored phase manifest, or ``None`` when it was never written."""

        storage_ref = phase_storage_ref(campaign_id, phase)
        artifact = await self._metadata.get_archive_artifact_by_storage_ref(storage_ref)
        if artifact is None:
            return None
        self._assert_artifact_bound(artifact, campaign_id=campaign_id, phase=phase)
        content = await self._artifacts.get(storage_ref)
        if content is None:
            raise LookupError("campaign phase artifact index has no stored content")
        if len(content) != artifact.byte_count:
            raise ValueError("campaign phase artifact byte count does not match its index")
        if "sha256:" + hashlib.sha256(content).hexdigest() != artifact.artifact_digest:
            raise ValueError("campaign phase artifact content does not match its digest")
        envelope = json.loads(content.decode())
        if not isinstance(envelope, dict):
            raise ValueError("campaign phase artifact MUST decode to an envelope mapping")
        self._assert_bound(envelope, campaign_id=campaign_id, phase=phase)
        manifest = envelope.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("campaign phase envelope MUST contain a manifest mapping")
        assert_sanitized(manifest)
        return manifest

    def _assert_artifact_bound(
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

    def _assert_bound(
        self,
        envelope: Mapping[str, object],
        *,
        campaign_id: str,
        phase: CampaignPhase,
    ) -> None:
        if envelope.get("scope_digest") != self._scope.digest:
            raise PermissionError("campaign phase artifact is bound to another scope")
        if envelope.get("purpose") != CAMPAIGN_PURPOSE:
            raise PermissionError("campaign phase artifact is bound to another purpose")
        if envelope.get("campaign_id") != campaign_id:
            raise ValueError("campaign phase artifact campaign identity is unexpected")
        if envelope.get("phase") != phase.value:
            raise ValueError("campaign phase artifact phase is unexpected")

    def _artifact(
        self,
        *,
        content_digest: str,
        byte_count: int,
        campaign_id: str,
        phase: CampaignPhase,
        manifest_digest: str,
        created_at: datetime,
    ) -> OperationalArchiveArtifact:
        body: dict[str, object] = {
            "artifact_digest": content_digest,
            "storage_ref": phase_storage_ref(campaign_id, phase),
            "manifest_digest": manifest_digest,
            "scope_refs": [self._scope.scope_ref],
            "allowed_purposes": [CAMPAIGN_PURPOSE],
            "byte_count": byte_count,
            "created_at": created_at.isoformat(),
        }
        return OperationalArchiveArtifact(
            artifact_digest=content_digest,
            storage_ref=str(body["storage_ref"]),
            manifest_digest=manifest_digest,
            scope_refs=(self._scope.scope_ref,),
            allowed_purposes=(CAMPAIGN_PURPOSE,),
            byte_count=byte_count,
            created_at=created_at,
            digest=evidence_digest(body),
        )

    def _manifest(
        self,
        manifest: Mapping[str, object],
        *,
        content_digest: str,
        campaign_id: str,
        phase: CampaignPhase,
        created_at: datetime,
    ) -> ArchiveManifest:
        ontology_release_digest = manifest.get("ontology_release_digest")
        if not isinstance(ontology_release_digest, str):
            raise ValueError("campaign phase manifest has no ontology release digest")
        source = ArchiveSourcePartition(
            partition_id=phase_key_digest(campaign_id, phase),
            content_digest=content_digest,
            interval_start=created_at,
            interval_end=created_at + timedelta(microseconds=1),
            object_count=0,
            relationship_count=0,
            schema_version="oi16-campaign-phase/1.0.0",
            ontology_release_digest=ontology_release_digest,
            complete=True,
        )
        return build_archive_manifest(
            (source,),
            archive_content_digest=content_digest,
            compression_profile="identity",
            encryption_profile="azure-storage-service",
            destination_class="private-blob",
            retention_class="oi16-certification-phase",
            creation_receipt_digest=phase_key_digest(campaign_id, phase),
            created_at=created_at,
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
    "PhaseManifestStore",
    "PhaseMetadataStore",
    "phase_key_digest",
    "phase_storage_ref",
]
