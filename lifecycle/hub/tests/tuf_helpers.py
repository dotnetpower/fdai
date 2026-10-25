"""Shared builders for the signed catalog role tests. Everything is synthetic."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
)
from fdai_deployment_cli.lifecycle_catalog_roles import root_to_wire

from fdai_lifecycle_hub.catalog_trust import (
    CatalogTrust,
    MetadataBundle,
    OnlineRoleKey,
    key_id_of,
    raw_public_key,
    sign_role,
)
from fdai_lifecycle_hub.signing import HubSigningKey


def new_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def ident(key: Ed25519PrivateKey) -> str:
    return key_id_of(key.public_key())


@dataclass
class Authority:
    """One ceremony's keys: offline root holders plus the online and export keys a root names."""

    root_keys: list[Ed25519PrivateKey] = field(
        default_factory=lambda: [new_key() for _ in range(3)]
    )
    threshold: int = 2
    snapshot: OnlineRoleKey = field(default_factory=lambda: OnlineRoleKey(new_key()))
    timestamp: OnlineRoleKey = field(default_factory=lambda: OnlineRoleKey(new_key()))

    def root(
        self,
        version: int,
        *,
        export_key: HubSigningKey,
        now: datetime,
        signers: list[Ed25519PrivateKey] | None = None,
        also_signed_by: list[Ed25519PrivateKey] | None = None,
        valid_days: int = 365,
        threshold: int | None = None,
    ) -> CatalogRootRecord:
        """Build a root signed by `signers` (default: a threshold of this authority's keys)."""

        threshold = threshold or self.threshold
        keys = {
            ident(key): raw_public_key(key.public_key())
            for key in [*self.root_keys, self.snapshot.private_key, self.timestamp.private_key]
        }
        export_id = key_id_of(export_key.public_key)
        keys[export_id] = raw_public_key(export_key.public_key)
        unsigned = CatalogRootRecord(
            version=version,
            threshold=threshold,
            root_key_ids=frozenset(ident(key) for key in self.root_keys),
            snapshot_key_ids=frozenset({self.snapshot.key_id}),
            timestamp_key_ids=frozenset({self.timestamp.key_id}),
            export_key_ids=frozenset({export_id}),
            public_keys=keys,
            signed_at=now,
            expires_at=now + timedelta(days=valid_days),
        )
        chosen = signers if signers is not None else self.root_keys[:threshold]
        return self.sign(unsigned, [*chosen, *(also_signed_by or [])])

    @staticmethod
    def sign(root: CatalogRootRecord, signers: list[Ed25519PrivateKey]) -> CatalogRootRecord:
        payload = root.canonical_payload()
        return replace(root, signatures={ident(key): sign_role(key, payload) for key in signers})

    def pin(self) -> CatalogTrust:
        return CatalogTrust(
            mode="tuf",
            root_key_ids=tuple(ident(key) for key in self.root_keys),
            root_threshold=self.threshold,
        )

    def bundle(
        self,
        chain: list[CatalogRootRecord],
        *,
        now: datetime,
        snapshot_version: int = 1,
        timestamp_version: int = 1,
        recall_sequences: tuple[int, ...] = (),
        export_digest: str = "0" * 64,
        export_revision: int = 1,
        channel_versions: dict[str, int] | None = None,
        timestamp_ttl: timedelta = timedelta(hours=24),
        snapshot_ttl: timedelta = timedelta(days=7),
        snapshot_signer: OnlineRoleKey | None = None,
        timestamp_signer: OnlineRoleKey | None = None,
    ) -> MetadataBundle:
        snapshot_key = snapshot_signer or self.snapshot
        timestamp_key = timestamp_signer or self.timestamp
        unsigned_snapshot = CatalogSnapshotRecord(
            version=snapshot_version,
            channel_versions=channel_versions or {"DEV": export_revision},
            recall_sequences=recall_sequences,
            key_id=self.snapshot.key_id,
            signed_at=now,
            expires_at=now + snapshot_ttl,
            export_digest=export_digest,
            export_revision=export_revision,
        )
        snapshot = replace(
            unsigned_snapshot, signature=snapshot_key.sign(unsigned_snapshot.canonical_payload())
        )
        unsigned_timestamp = CatalogTimestampRecord(
            version=timestamp_version,
            snapshot_version=snapshot.version,
            snapshot_digest=snapshot.digest,
            key_id=self.timestamp.key_id,
            signed_at=now,
            expires_at=now + timestamp_ttl,
        )
        timestamp = replace(
            unsigned_timestamp,
            signature=timestamp_key.sign(unsigned_timestamp.canonical_payload()),
        )
        return MetadataBundle(tuple(chain), snapshot, timestamp)


def wire(root: CatalogRootRecord) -> dict[str, object]:
    return root_to_wire(root)
