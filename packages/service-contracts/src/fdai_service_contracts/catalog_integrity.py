"""TUF-style signed catalog root, snapshot, and timestamp integrity evaluators."""

from __future__ import annotations

import hashlib
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from fdai_service_contracts.catalog_canonical import (
    SignatureVerifier,
    canonical_bytes,
    canonical_digest,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} MUST include timezone information")


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} MUST be a positive integer")


KEY_ID_PREFIX = "ed25519-"
ED25519_PUBLIC_KEY_BYTES = 32
MAX_ROOT_CHAIN_LENGTH = 32
# Every role signature has its own domain, so a signature made for one role or for an export
# cannot be replayed as another. The export domain lives with the export signature itself.
ROLE_SIGNATURE_DOMAINS: Mapping[str, bytes] = {
    "root": b"fdai.catalog-root.v1\n",
    "snapshot": b"fdai.catalog-snapshot.v1\n",
    "timestamp": b"fdai.catalog-timestamp.v1\n",
}


def catalog_key_id(raw_public_key: bytes) -> str:
    """Self-certifying key id: the full SHA-256 of the raw Ed25519 public key."""

    return KEY_ID_PREFIX + hashlib.sha256(raw_public_key).hexdigest()


def role_signing_message(role: str, payload: bytes) -> bytes:
    """Domain-separate one role signature. An unknown role has no signing domain."""

    try:
        return ROLE_SIGNATURE_DOMAINS[role] + payload
    except KeyError:
        raise ValueError(f"unknown catalog role: {role}") from None


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogRootRecord:
    """Signed TUF root role record naming authorized keys and threshold."""

    version: int
    threshold: int
    root_key_ids: frozenset[str]
    snapshot_key_ids: frozenset[str]
    timestamp_key_ids: frozenset[str]
    signed_at: datetime
    expires_at: datetime
    signatures: Mapping[str, bytes] = field(default_factory=dict)
    # Optional extensions. Records that omit them keep their original canonical payload.
    export_key_ids: frozenset[str] = frozenset()
    public_keys: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_positive_int(self.version, "version")
        _require_positive_int(self.threshold, "threshold")
        if not self.root_key_ids or not self.snapshot_key_ids or not self.timestamp_key_ids:
            raise ValueError("root, snapshot, and timestamp key sets MUST NOT be empty")
        _require_aware(self.signed_at, "signed_at")
        _require_aware(self.expires_at, "expires_at")
        if self.signed_at >= self.expires_at:
            raise ValueError("signed_at MUST precede expires_at")
        if self.public_keys:
            named = (
                self.root_key_ids
                | self.snapshot_key_ids
                | self.timestamp_key_ids
                | self.export_key_ids
            )
            if named != set(self.public_keys):
                raise ValueError("public_keys MUST cover exactly the keys the roles name")
            for key_id, raw in self.public_keys.items():
                if len(raw) != ED25519_PUBLIC_KEY_BYTES or key_id != catalog_key_id(raw):
                    raise ValueError("public key does not match its self-certifying key id")

    def to_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "role": "root",
            "version": self.version,
            "threshold": self.threshold,
            "root_key_ids": sorted(self.root_key_ids),
            "snapshot_key_ids": sorted(self.snapshot_key_ids),
            "timestamp_key_ids": sorted(self.timestamp_key_ids),
            "signed_at": self.signed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }
        if self.export_key_ids:
            mapping["export_key_ids"] = sorted(self.export_key_ids)
        if self.public_keys:
            mapping["public_keys"] = {
                key_id: b64encode(raw).decode("ascii")
                for key_id, raw in sorted(self.public_keys.items())
            }
        return mapping

    def canonical_payload(self) -> bytes:
        return canonical_bytes(self.to_mapping())

    @property
    def digest(self) -> str:
        """Digest of the signed payload, used to detect two different roots at one version."""

        return f"sha256:{canonical_digest(self.to_mapping())}"


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogSnapshotRecord:
    """Signed TUF snapshot role record listing channel versions and recall sequence numbers."""

    version: int
    channel_versions: Mapping[str, int]
    recall_sequences: tuple[int, ...] = ()
    release_digests: Mapping[str, str] = field(default_factory=dict)
    key_id: str
    signed_at: datetime
    expires_at: datetime
    signature: bytes = b""
    # Optional export binding. Records that omit it keep their original canonical payload.
    export_digest: str | None = None
    export_revision: int | None = None

    def __post_init__(self) -> None:
        _require_positive_int(self.version, "version")
        if not self.key_id.strip():
            raise ValueError("key_id MUST NOT be empty")
        _require_aware(self.signed_at, "signed_at")
        _require_aware(self.expires_at, "expires_at")
        if self.signed_at >= self.expires_at:
            raise ValueError("signed_at MUST precede expires_at")
        for seq in self.recall_sequences:
            _require_positive_int(seq, "recall_sequence")
        if self.export_revision is not None and (
            isinstance(self.export_revision, bool) or self.export_revision < 0
        ):
            raise ValueError("export_revision MUST be a non-negative integer")

    def to_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "role": "snapshot",
            "version": self.version,
            "channel_versions": dict(sorted(self.channel_versions.items())),
            "recall_sequences": list(self.recall_sequences),
            "release_digests": dict(sorted(self.release_digests.items())),
            "key_id": self.key_id,
            "signed_at": self.signed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }
        if self.export_digest is not None:
            mapping["export_digest"] = self.export_digest
        if self.export_revision is not None:
            mapping["export_revision"] = self.export_revision
        return mapping

    def canonical_payload(self) -> bytes:
        return canonical_bytes(self.to_mapping())

    @property
    def digest(self) -> str:
        return f"sha256:{canonical_digest(self.to_mapping())}"


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogTimestampRecord:
    """Signed TUF timestamp role record naming the current snapshot and short expiry."""

    version: int
    snapshot_version: int
    snapshot_digest: str
    key_id: str
    signed_at: datetime
    expires_at: datetime
    signature: bytes = b""

    def __post_init__(self) -> None:
        _require_positive_int(self.version, "version")
        _require_positive_int(self.snapshot_version, "snapshot_version")
        if not self.snapshot_digest.strip() or not self.key_id.strip():
            raise ValueError("snapshot_digest and key_id MUST NOT be empty")
        _require_aware(self.signed_at, "signed_at")
        _require_aware(self.expires_at, "expires_at")
        if self.signed_at >= self.expires_at:
            raise ValueError("signed_at MUST precede expires_at")

    def to_mapping(self) -> dict[str, object]:
        return {
            "role": "timestamp",
            "version": self.version,
            "snapshot_version": self.snapshot_version,
            "snapshot_digest": self.snapshot_digest,
            "key_id": self.key_id,
            "signed_at": self.signed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def canonical_payload(self) -> bytes:
        return canonical_bytes(self.to_mapping())


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogIntegrityDecision:
    """Result of verifying signed root, snapshot, and timestamp catalog records."""

    allowed: bool
    reason_code: str
    expired: bool = False
    allowed_plan_types: frozenset[str] = field(default_factory=frozenset)
    demote_operator_overrides_to_shadow: bool = False
    alert_code: str | None = None

    def allows_plan_type(self, plan_type: str) -> bool:
        return self.allowed and plan_type in self.allowed_plan_types


_ALL_PLAN_TYPES = frozenset(
    {
        "install",
        "upgrade",
        "configuration-change",
        "recall-rolloff",
        "rollback",
        "drift-reconciliation",
    }
)


def evaluate_catalog_integrity(
    *,
    root: CatalogRootRecord,
    snapshot: CatalogSnapshotRecord,
    timestamp: CatalogTimestampRecord,
    verify_signature: SignatureVerifier,
    trusted_now: datetime,
    minimum_root_version: int = 1,
    minimum_snapshot_version: int = 1,
    minimum_timestamp_version: int = 1,
    previous_max_recall_sequence: int = 0,
) -> CatalogIntegrityDecision:
    """Verify role signatures, monotonic versions, recall sequence continuity, and expiry."""

    _require_aware(trusted_now, "trusted_now")
    if (
        root.version < minimum_root_version
        or snapshot.version < minimum_snapshot_version
        or timestamp.version < minimum_timestamp_version
    ):
        return CatalogIntegrityDecision(allowed=False, reason_code="catalog_version_rollback")

    root_payload = root.canonical_payload()
    valid_root_signers = {
        key_id
        for key_id, sig in root.signatures.items()
        if key_id in root.root_key_ids and bool(verify_signature(key_id, root_payload, sig))
    }
    if len(valid_root_signers) < root.threshold:
        return CatalogIntegrityDecision(allowed=False, reason_code="catalog_root_signature_invalid")
    if trusted_now >= root.expires_at:
        return CatalogIntegrityDecision(allowed=False, reason_code="catalog_root_expired")

    if snapshot.key_id not in root.snapshot_key_ids or not bool(
        verify_signature(snapshot.key_id, snapshot.canonical_payload(), snapshot.signature)
    ):
        return CatalogIntegrityDecision(
            allowed=False, reason_code="catalog_snapshot_signature_invalid"
        )

    if timestamp.key_id not in root.timestamp_key_ids or not bool(
        verify_signature(timestamp.key_id, timestamp.canonical_payload(), timestamp.signature)
    ):
        return CatalogIntegrityDecision(
            allowed=False, reason_code="catalog_timestamp_signature_invalid"
        )

    if (
        timestamp.snapshot_version != snapshot.version
        or timestamp.snapshot_digest != snapshot.digest
    ):
        return CatalogIntegrityDecision(allowed=False, reason_code="timestamp_snapshot_mismatch")

    expected_sequence = 1
    for seq in snapshot.recall_sequences:
        if seq != expected_sequence:
            return CatalogIntegrityDecision(allowed=False, reason_code="recall_sequence_gap")
        expected_sequence += 1
    current_max_recall = snapshot.recall_sequences[-1] if snapshot.recall_sequences else 0
    if current_max_recall < previous_max_recall_sequence:
        return CatalogIntegrityDecision(allowed=False, reason_code="recall_sequence_gap")

    if trusted_now >= timestamp.expires_at or trusted_now >= snapshot.expires_at:
        return CatalogIntegrityDecision(
            allowed=True,
            reason_code="catalog_timestamp_expired",
            expired=True,
            allowed_plan_types=frozenset({"recall-rolloff"}),
            demote_operator_overrides_to_shadow=True,
            alert_code="catalog_timestamp_expired",
        )

    return CatalogIntegrityDecision(
        allowed=True,
        reason_code="allowed",
        expired=False,
        allowed_plan_types=_ALL_PLAN_TYPES,
        demote_operator_overrides_to_shadow=False,
        alert_code=None,
    )
