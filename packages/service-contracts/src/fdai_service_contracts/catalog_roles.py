"""Wire form of the signed catalog roles and the root-chain rules, without any cryptography.

The signature primitive is injected, so this module stays pure and shared by the Release Hub
(which builds and serves roles) and the Lifecycle Hub (which verifies them).
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai_service_contracts.catalog_integrity import (
    MAX_ROOT_CHAIN_LENGTH,
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
)
from fdai_service_contracts.catalog_canonical import SignatureVerifier

ED25519_SIGNATURE_BYTES = 64
RootVerifierFactory = Callable[[Mapping[str, bytes]], SignatureVerifier]

_ROOT_FIELDS = frozenset(
    {
        "role",
        "version",
        "threshold",
        "root_key_ids",
        "snapshot_key_ids",
        "timestamp_key_ids",
        "signed_at",
        "expires_at",
        "signatures",
    }
)
_ROOT_OPTIONAL = frozenset({"export_key_ids", "public_keys"})
_SNAPSHOT_FIELDS = frozenset(
    {
        "role",
        "version",
        "channel_versions",
        "recall_sequences",
        "release_digests",
        "key_id",
        "signed_at",
        "expires_at",
        "signature",
    }
)
_SNAPSHOT_OPTIONAL = frozenset({"export_digest", "export_revision"})
_TIMESTAMP_FIELDS = frozenset(
    {
        "role",
        "version",
        "snapshot_version",
        "snapshot_digest",
        "key_id",
        "signed_at",
        "expires_at",
        "signature",
    }
)


class CatalogRootChainError(ValueError):
    """A root chain failed verification. `reason_code` is stable and safe to expose."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _document(value: object, role: str, required: frozenset[str], optional: frozenset[str]) -> Any:
    if not isinstance(value, dict) or value.get("role") != role:
        raise ValueError(f"catalog {role} record is invalid")
    keys = set(value)
    if not required <= keys or keys - required - optional:
        raise ValueError(f"catalog {role} record has unexpected fields")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} MUST be a non-empty string")
    return value


def _instant(value: object, name: str) -> datetime:
    try:
        return datetime.fromisoformat(_text(value, name))
    except ValueError:
        raise ValueError(f"{name} MUST be an ISO 8601 timestamp") from None


def _id_set(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} MUST be a list of key ids")
    result = frozenset(value)
    if len(result) != len(value):
        raise ValueError(f"{name} MUST NOT repeat a key id")
    return result


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} MUST be an integer")
    return value


def _bytes(value: object, name: str) -> bytes:
    try:
        return b64decode(_text(value, name), validate=True)
    except ValueError:
        raise ValueError(f"{name} MUST be base64") from None


def _signature(value: object, name: str) -> bytes:
    raw = _bytes(value, name)
    if len(raw) != ED25519_SIGNATURE_BYTES:
        raise ValueError(f"{name} MUST be an Ed25519 signature")
    return raw


def root_to_wire(root: CatalogRootRecord) -> dict[str, object]:
    return {
        **root.to_mapping(),
        "signatures": {
            key_id: b64encode(raw).decode("ascii")
            for key_id, raw in sorted(root.signatures.items())
        },
    }


def root_from_wire(value: object) -> CatalogRootRecord:
    document = _document(value, "root", _ROOT_FIELDS, _ROOT_OPTIONAL)
    signatures = document["signatures"]
    keys = document.get("public_keys", {})
    if not isinstance(signatures, dict) or not isinstance(keys, dict):
        raise ValueError("catalog root signatures and keys MUST be objects")
    return CatalogRootRecord(
        version=_integer(document["version"], "version"),
        threshold=_integer(document["threshold"], "threshold"),
        root_key_ids=_id_set(document["root_key_ids"], "root_key_ids"),
        snapshot_key_ids=_id_set(document["snapshot_key_ids"], "snapshot_key_ids"),
        timestamp_key_ids=_id_set(document["timestamp_key_ids"], "timestamp_key_ids"),
        export_key_ids=_id_set(document.get("export_key_ids", []), "export_key_ids"),
        signed_at=_instant(document["signed_at"], "signed_at"),
        expires_at=_instant(document["expires_at"], "expires_at"),
        public_keys={_text(k, "key id"): _bytes(v, "public key") for k, v in keys.items()},
        signatures={_text(k, "key id"): _signature(v, "signature") for k, v in signatures.items()},
    )


def snapshot_to_wire(snapshot: CatalogSnapshotRecord) -> dict[str, object]:
    return {**snapshot.to_mapping(), "signature": b64encode(snapshot.signature).decode("ascii")}


def snapshot_from_wire(value: object) -> CatalogSnapshotRecord:
    document = _document(value, "snapshot", _SNAPSHOT_FIELDS, _SNAPSHOT_OPTIONAL)
    versions, sequences = document["channel_versions"], document["recall_sequences"]
    digests = document["release_digests"]
    if (
        not isinstance(versions, dict)
        or not isinstance(digests, dict)
        or not isinstance(sequences, list)
    ):
        raise ValueError("catalog snapshot collections are invalid")
    revision = document.get("export_revision")
    return CatalogSnapshotRecord(
        version=_integer(document["version"], "version"),
        channel_versions={
            _text(k, "channel"): _integer(v, "channel version") for k, v in versions.items()
        },
        recall_sequences=tuple(_integer(item, "recall sequence") for item in sequences),
        release_digests={
            _text(k, "release"): _text(v, "release digest") for k, v in digests.items()
        },
        key_id=_text(document["key_id"], "key_id"),
        signed_at=_instant(document["signed_at"], "signed_at"),
        expires_at=_instant(document["expires_at"], "expires_at"),
        signature=_signature(document["signature"], "signature"),
        export_digest=_text(document["export_digest"], "export_digest")
        if "export_digest" in document
        else None,
        export_revision=None if revision is None else _integer(revision, "export_revision"),
    )


def timestamp_to_wire(timestamp: CatalogTimestampRecord) -> dict[str, object]:
    return {**timestamp.to_mapping(), "signature": b64encode(timestamp.signature).decode("ascii")}


def timestamp_from_wire(value: object) -> CatalogTimestampRecord:
    document = _document(value, "timestamp", _TIMESTAMP_FIELDS, frozenset())
    return CatalogTimestampRecord(
        version=_integer(document["version"], "version"),
        snapshot_version=_integer(document["snapshot_version"], "snapshot_version"),
        snapshot_digest=_text(document["snapshot_digest"], "snapshot_digest"),
        key_id=_text(document["key_id"], "key_id"),
        signed_at=_instant(document["signed_at"], "signed_at"),
        expires_at=_instant(document["expires_at"], "expires_at"),
        signature=_signature(document["signature"], "signature"),
    )


def _threshold_met(
    root_key_ids: frozenset[str],
    threshold: int,
    signatures: Mapping[str, bytes],
    payload: bytes,
    verify: SignatureVerifier,
) -> bool:
    signers = {
        key_id
        for key_id, signature in signatures.items()
        if key_id in root_key_ids and bool(verify(key_id, payload, signature))
    }
    return len(signers) >= threshold


def verify_root_chain(
    chain: Sequence[CatalogRootRecord],
    *,
    pinned_root_key_ids: frozenset[str],
    pinned_threshold: int,
    make_verifier: RootVerifierFactory,
) -> CatalogRootRecord:
    """Verify consecutive roots from the pinned first root and return the newest one.

    The first root MUST name exactly the pinned keys and threshold and be signed by a threshold
    of them. Each later root MUST be signed by a threshold of the previous root's keys and by a
    threshold of its own keys, so no key set can take over without the previous holders.
    Intermediate roots may be expired, because only the newest root is trusted for use.
    """

    if not chain or len(chain) > MAX_ROOT_CHAIN_LENGTH:
        raise CatalogRootChainError("catalog_root_chain_invalid")
    previous: CatalogRootRecord | None = None
    for expected_version, root in enumerate(chain, start=1):
        if root.version != expected_version or not root.public_keys:
            raise CatalogRootChainError("catalog_root_chain_invalid")
        payload = root.canonical_payload()
        if previous is None:
            if root.root_key_ids != pinned_root_key_ids or root.threshold != pinned_threshold:
                raise CatalogRootChainError("catalog_root_pin_mismatch")
        elif not _threshold_met(
            previous.root_key_ids,
            previous.threshold,
            root.signatures,
            payload,
            make_verifier(previous.public_keys),
        ):
            raise CatalogRootChainError("catalog_root_rotation_unsigned_by_previous")
        if not _threshold_met(
            root.root_key_ids,
            root.threshold,
            root.signatures,
            payload,
            make_verifier(root.public_keys),
        ):
            raise CatalogRootChainError("catalog_root_signature_invalid")
        previous = root
    return chain[-1]
