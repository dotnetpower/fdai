"""Signed catalog metadata bundle and role signature verification, shared by every verifier.

The Lifecycle Hub and an installation's Core verify the same bytes with the same domain-separation
rule. Nothing here touches the network, a clock, or persistence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fdai_service_contracts.catalog_canonical import canonical_bytes
from fdai_service_contracts.catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    role_signing_message,
)
from fdai_service_contracts.catalog_roles import (
    root_from_wire,
    root_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    timestamp_from_wire,
    timestamp_to_wire,
)
from fdai_service_contracts.catalog_canonical import SignatureVerifier

MAX_METADATA_BYTES = 1024 * 1024
METADATA_SCHEMA = "fdai.catalog-metadata.v1"


def role_of(payload: bytes) -> str | None:
    try:
        role = json.loads(payload).get("role")
    except (ValueError, AttributeError):
        return None
    return role if isinstance(role, str) else None


def role_verifier(public_keys: Mapping[str, bytes]) -> SignatureVerifier:
    """Verify a role signature with a key named by id, in the signed payload's own role domain."""

    keys = dict(public_keys)

    def verify(key_id: str, payload: bytes, signature: bytes) -> bool:
        raw = keys.get(key_id)
        role = role_of(payload)
        if raw is None or role is None:
            return False
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(
                signature, role_signing_message(role, payload)
            )
        except (InvalidSignature, ValueError):
            return False
        return True

    return verify


@dataclass(frozen=True, slots=True)
class MetadataBundle:
    """The root chain, snapshot and timestamp served together from one consistent state."""

    root_chain: tuple[CatalogRootRecord, ...]
    snapshot: CatalogSnapshotRecord
    timestamp: CatalogTimestampRecord

    def to_bytes(self) -> bytes:
        return canonical_bytes(
            {
                "schema": METADATA_SCHEMA,
                "root_chain": [root_to_wire(root) for root in self.root_chain],
                "snapshot": snapshot_to_wire(self.snapshot),
                "timestamp": timestamp_to_wire(self.timestamp),
            }
        )


def parse_metadata(raw: bytes) -> MetadataBundle:
    """Parse untrusted metadata bytes. Signatures are verified separately."""

    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Catalog metadata is too large.")
    try:
        document = json.loads(raw)
        if (
            not isinstance(document, dict)
            or set(document) != {"schema", "root_chain", "snapshot", "timestamp"}
            or document["schema"] != METADATA_SCHEMA
            or not isinstance(document["root_chain"], list)
        ):
            raise ValueError
        return MetadataBundle(
            root_chain=tuple(root_from_wire(item) for item in document["root_chain"]),
            snapshot=snapshot_from_wire(document["snapshot"]),
            timestamp=timestamp_from_wire(document["timestamp"]),
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("Catalog metadata is malformed.") from None
