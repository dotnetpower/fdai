"""Lifecycle Hub verification of signed catalog roles against persisted anti-rollback floors.

Pure functions over bytes and records: the caller owns the network, the clock and persistence.
Every failure returns a stable reason code and `verified=False`, so nothing here can adopt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_service_contracts.catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    evaluate_catalog_integrity,
)
from fdai_service_contracts.catalog_roles import (
    CatalogRootChainError,
    verify_root_chain,
)

from fdai_lifecycle_hub.catalog_import import verify_export_signature
from fdai_lifecycle_hub.catalog_trust import (
    CatalogTrust,
    MetadataBundle,
    role_verifier,
)


def payload_digest(
    record: CatalogRootRecord | CatalogSnapshotRecord | CatalogTimestampRecord,
) -> str:
    """Lowercase SHA-256 of the signed payload, which excludes the signatures."""

    return hashlib.sha256(record.canonical_payload()).hexdigest()


def release_digest(manifest: str) -> str:
    return "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class IntegrityFloors:
    """What this Hub has already verified. Newer metadata may never fall below it."""

    root_version: int = 0
    root_digest: str | None = None
    snapshot_version: int = 0
    snapshot_digest: str | None = None
    timestamp_version: int = 0
    timestamp_digest: str | None = None
    max_recall_sequence: int = 0
    channel_versions: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntegrityAssessment:
    verified: bool
    reason_code: str
    root: CatalogRootRecord | None = None
    snapshot: CatalogSnapshotRecord | None = None
    timestamp: CatalogTimestampRecord | None = None
    expired: bool = False
    root_rotation: bool = False
    previous_root_version: int = 0
    allowed_plan_types: frozenset[str] = frozenset()
    demote_operator_overrides_to_shadow: bool = False

    def to_json(self) -> dict[str, Any]:
        """Operator-visible state. It carries versions and expiries, never keys or signatures."""

        def role(record: Any) -> dict[str, Any] | None:
            if record is None:
                return None
            return {"version": record.version, "expires_at": record.expires_at.isoformat()}

        return {
            "mode": "tuf",
            "verified": self.verified,
            "reason": self.reason_code,
            "root": role(self.root),
            "snapshot": role(self.snapshot),
            "timestamp": role(self.timestamp),
            "expired": self.expired,
            "root_rotation": self.root_rotation,
            "previous_root_version": self.previous_root_version,
            "max_recall_sequence": max(self.snapshot.recall_sequences, default=0)
            if self.snapshot
            else 0,
            "allowed_plan_types": sorted(self.allowed_plan_types),
            "demote_operator_overrides_to_shadow": self.demote_operator_overrides_to_shadow,
        }

    def policy_facts(self) -> dict[str, Any]:
        """The only integrity facts the Rego policy sees."""

        return {
            "mode": "tuf",
            "verified": self.verified,
            "expired": self.expired,
            "root_rotation": self.root_rotation,
            "reason": self.reason_code,
            "allowed_plan_types": sorted(self.allowed_plan_types),
        }


def _failed(reason: str, **known: Any) -> IntegrityAssessment:
    return IntegrityAssessment(verified=False, reason_code=reason, **known)


def assess_roles(
    bundle: MetadataBundle,
    *,
    trust: CatalogTrust,
    floors: IntegrityFloors,
    now: datetime,
) -> IntegrityAssessment:
    """Verify the root chain, snapshot and timestamp. The export is bound separately."""

    try:
        root = verify_root_chain(
            bundle.root_chain,
            pinned_root_key_ids=trust.root_key_id_set,
            pinned_threshold=trust.root_threshold,
            make_verifier=role_verifier,
        )
    except CatalogRootChainError as error:
        return _failed(error.reason_code)
    snapshot, timestamp = bundle.snapshot, bundle.timestamp
    known = {"root": root, "snapshot": snapshot, "timestamp": timestamp}
    if not root.export_key_ids:
        return _failed("catalog_root_export_key_missing", **known)
    if root.version < floors.root_version:
        return _failed("catalog_version_rollback", **known)
    if floors.root_version:
        anchored = bundle.root_chain[floors.root_version - 1]
        if payload_digest(anchored) != floors.root_digest:
            return _failed("catalog_root_equivocation", **known)
    if (
        snapshot.version == floors.snapshot_version
        and payload_digest(snapshot) != floors.snapshot_digest
    ):
        return _failed("catalog_snapshot_equivocation", **known)
    if (
        timestamp.version == floors.timestamp_version
        and payload_digest(timestamp) != floors.timestamp_digest
    ):
        return _failed("catalog_timestamp_equivocation", **known)
    decision = evaluate_catalog_integrity(
        root=root,
        snapshot=snapshot,
        timestamp=timestamp,
        verify_signature=role_verifier(root.public_keys),
        trusted_now=now,
        minimum_root_version=max(1, floors.root_version),
        minimum_snapshot_version=max(1, floors.snapshot_version),
        minimum_timestamp_version=max(1, floors.timestamp_version),
        previous_max_recall_sequence=floors.max_recall_sequence,
    )
    if not decision.allowed:
        return _failed(decision.reason_code, **known)
    return IntegrityAssessment(
        verified=True,
        reason_code=decision.reason_code,
        root=root,
        snapshot=snapshot,
        timestamp=timestamp,
        expired=decision.expired,
        root_rotation=floors.root_version > 0 and root.version > floors.root_version,
        previous_root_version=floors.root_version,
        allowed_plan_types=decision.allowed_plan_types,
        demote_operator_overrides_to_shadow=decision.demote_operator_overrides_to_shadow,
    )


def export_keys(root: CatalogRootRecord) -> tuple[Ed25519PublicKey, ...]:
    """The keys the root authorizes to sign the export and the Release manifests."""

    return tuple(
        Ed25519PublicKey.from_public_bytes(root.public_keys[key_id])
        for key_id in sorted(root.export_key_ids)
    )


def export_signature_verified(raw: bytes, signature: str | None, root: CatalogRootRecord) -> bool:
    return any(verify_export_signature(raw, signature, key) for key in export_keys(root))


def bind_export(
    assessment: IntegrityAssessment,
    *,
    raw: bytes,
    floors: IntegrityFloors,
) -> str | None:
    """Return a reason code when the snapshot does not describe exactly these export bytes."""

    snapshot = assessment.snapshot
    if not assessment.verified or snapshot is None:
        return "integrity_not_verified"
    if snapshot.export_digest != hashlib.sha256(raw).hexdigest():
        return "export_digest_mismatch"
    try:
        document = json.loads(raw)
        revision, channels = document["revision"], document["channels"]
        releases, recalls = document["releases"], document["recalls"]
        mismatch = (
            snapshot.export_revision != revision
            or set(snapshot.channel_versions) != set(channels)
            or {
                release_id: release_digest(artifact["manifest"])
                for release_id, artifact in releases.items()
            }
            != dict(snapshot.release_digests)
            or len(recalls) != len(snapshot.recall_sequences)
            or [item["sequence"] for item in recalls]
            != sorted({item["sequence"] for item in recalls})
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return "snapshot_export_mismatch"
    if mismatch:
        return "snapshot_export_mismatch"
    if any(
        version < floors.channel_versions.get(channel, 0)
        for channel, version in snapshot.channel_versions.items()
    ):
        return "catalog_version_rollback"
    return None


def verified_records(
    assessment: IntegrityAssessment,
) -> tuple[CatalogRootRecord, CatalogSnapshotRecord, CatalogTimestampRecord]:
    """The records of a verified assessment, and only those."""

    root, snapshot, timestamp = assessment.root, assessment.snapshot, assessment.timestamp
    if not assessment.verified or root is None or snapshot is None or timestamp is None:
        raise ValueError("Only verified catalog integrity can advance the floors.")
    return root, snapshot, timestamp


def advanced_floors(assessment: IntegrityAssessment) -> IntegrityFloors:
    """Floors after accepting this assessment. Only a verified assessment may advance them."""

    root, snapshot, timestamp = verified_records(assessment)
    return IntegrityFloors(
        root_version=root.version,
        root_digest=payload_digest(root),
        snapshot_version=snapshot.version,
        snapshot_digest=payload_digest(snapshot),
        timestamp_version=timestamp.version,
        timestamp_digest=payload_digest(timestamp),
        max_recall_sequence=max(snapshot.recall_sequences, default=0),
        channel_versions=dict(snapshot.channel_versions),
    )
