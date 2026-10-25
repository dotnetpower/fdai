"""TUF-style catalog trust: the pinned initial root, role signing and role verification.

The Release Hub signs with these helpers and the Lifecycle Hub verifies with them, so both sides
share one domain-separation rule. Verification never touches the network or a database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    catalog_key_id,
    role_signing_message,
)
from fdai_deployment_cli.lifecycle_catalog_roles import (
    root_from_wire,
    root_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    timestamp_from_wire,
    timestamp_to_wire,
)
from fdai_deployment_cli.lifecycle_plan import SignatureVerifier
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_METADATA_BYTES = 1024 * 1024
METADATA_SCHEMA = "fdai.catalog-metadata.v1"
_KEY_ID = re.compile(r"^ed25519-[0-9a-f]{64}$")


class CatalogTrust(BaseModel):
    """The initial root a Lifecycle Hub trusts: its offline key ids and signing threshold.

    The pin names keys, not a Release Hub address. Every later root must be signed by a
    threshold of the keys of the root before it, so the pin never has to change for a rotation.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    mode: Literal["tuf"]
    root_key_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    root_threshold: int = Field(ge=1, le=16)

    @model_validator(mode="after")
    def validate_pin(self) -> CatalogTrust:
        if any(_KEY_ID.fullmatch(key_id) is None for key_id in self.root_key_ids):
            raise ValueError("Catalog root pins must be ed25519 key ids.")
        if len(set(self.root_key_ids)) != len(self.root_key_ids):
            raise ValueError("Catalog root pins must be unique.")
        if self.root_threshold > len(self.root_key_ids):
            raise ValueError("Catalog root threshold exceeds the pinned key count.")
        return self

    @property
    def root_key_id_set(self) -> frozenset[str]:
        return frozenset(self.root_key_ids)

    @property
    def key_digest(self) -> str:
        """Stable identity of the pin, persisted so a changed pin cannot silently replace it."""

        return canonical_digest_hex(
            {
                "mode": self.mode,
                "root_key_ids": sorted(self.root_key_ids),
                "root_threshold": self.root_threshold,
            }
        )


def canonical_digest_hex(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_public_key(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id_of(public_key: Ed25519PublicKey) -> str:
    return catalog_key_id(raw_public_key(public_key))


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


def sign_role(private_key: Ed25519PrivateKey, payload: bytes) -> bytes:
    """Sign one role payload in the domain its own `role` field selects."""

    role = role_of(payload)
    if role is None:
        raise ValueError("catalog role payload names no role")
    return private_key.sign(role_signing_message(role, payload))


@dataclass(frozen=True, slots=True)
class OnlineRoleKey:
    """An online snapshot or timestamp key. It is never the offline root key."""

    private_key: Ed25519PrivateKey

    @property
    def key_id(self) -> str:
        return key_id_of(self.private_key.public_key())

    def sign(self, payload: bytes) -> bytes:
        return sign_role(self.private_key, payload)


def online_key_from_environment(name: str) -> OnlineRoleKey:
    """Read a secret-referenced PEM key once and remove it from the process environment."""

    value = os.environ.pop(name, "")
    if not value:
        raise ValueError("Provision the catalog role key through a secret reference.")
    key = serialization.load_pem_private_key(value.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Catalog role keys must be Ed25519.")
    return OnlineRoleKey(key)


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
