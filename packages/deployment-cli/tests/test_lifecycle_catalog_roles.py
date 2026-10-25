"""Wire form and root-chain rules for signed catalog roles (#2489)."""

from __future__ import annotations

import hashlib
import json
from base64 import b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fdai_deployment_cli.lifecycle_catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    catalog_key_id,
    role_signing_message,
)
from fdai_deployment_cli.lifecycle_catalog_roles import (
    CatalogRootChainError,
    root_from_wire,
    root_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    timestamp_from_wire,
    timestamp_to_wire,
    verify_root_chain,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def _key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())


def _raw(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _ident(key: Ed25519PrivateKey) -> str:
    return catalog_key_id(_raw(key))


def _verifier(public_keys):
    def verify(key_id: str, payload: bytes, signature: bytes) -> bool:
        raw = public_keys.get(key_id)
        if raw is None:
            return False
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(
                signature, role_signing_message(json.loads(payload)["role"], payload)
            )
        except Exception:  # noqa: BLE001 - any failure is a rejected signature
            return False
        return True

    return verify


def _root(version: int, holders: list[Ed25519PrivateKey], signers, threshold: int = 2):
    online = [_key("snapshot"), _key("timestamp"), _key("export")]
    keys = {_ident(key): _raw(key) for key in [*holders, *online]}
    unsigned = CatalogRootRecord(
        version=version,
        threshold=threshold,
        root_key_ids=frozenset(_ident(key) for key in holders),
        snapshot_key_ids=frozenset({_ident(online[0])}),
        timestamp_key_ids=frozenset({_ident(online[1])}),
        export_key_ids=frozenset({_ident(online[2])}),
        public_keys=keys,
        signed_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    payload = unsigned.canonical_payload()
    return replace(
        unsigned,
        signatures={
            _ident(key): key.sign(role_signing_message("root", payload)) for key in signers
        },
    )


def _chain_args(first: CatalogRootRecord):
    return {
        "pinned_root_key_ids": first.root_key_ids,
        "pinned_threshold": first.threshold,
        "make_verifier": _verifier,
    }


def test_chain_accepts_a_threshold_signed_root_and_a_rotation_signed_by_both_sets():
    old = [_key(f"old-{i}") for i in range(3)]
    new = [_key(f"new-{i}") for i in range(3)]
    first = _root(1, old, old[:2])
    second = _root(2, new, [*new[:2], *old[:2]])
    assert verify_root_chain([first], **_chain_args(first)) is first
    assert verify_root_chain([first, second], **_chain_args(first)) is second


@pytest.mark.parametrize(
    ("label", "signers", "reason"),
    [
        ("only the new holders", "new", "catalog_root_rotation_unsigned_by_previous"),
        ("one old holder", "one-old", "catalog_root_rotation_unsigned_by_previous"),
        ("only the old holders", "old", "catalog_root_signature_invalid"),
    ],
)
def test_rotation_needs_both_thresholds(label, signers, reason):
    old = [_key(f"old-{i}") for i in range(3)]
    new = [_key(f"new-{i}") for i in range(3)]
    first = _root(1, old, old[:2])
    chosen = {"new": new[:2], "one-old": [*new[:2], old[0]], "old": old[:2]}[signers]
    with pytest.raises(CatalogRootChainError) as raised:
        verify_root_chain([first, _root(2, new, chosen)], **_chain_args(first))
    assert raised.value.reason_code == reason, label


def test_chain_rejects_a_foreign_first_root_gaps_and_unbounded_length():
    holders = [_key(f"h-{i}") for i in range(3)]
    first = _root(1, holders, holders[:2])
    other = _root(1, [_key(f"x-{i}") for i in range(3)], [_key(f"x-{i}") for i in range(2)])
    with pytest.raises(CatalogRootChainError) as raised:
        verify_root_chain([other], **_chain_args(first))
    assert raised.value.reason_code == "catalog_root_pin_mismatch"
    for chain in ([], [_root(2, holders, holders[:2])], [first] * 40):
        with pytest.raises(CatalogRootChainError) as raised:
            verify_root_chain(chain, **_chain_args(first))
        assert raised.value.reason_code == "catalog_root_chain_invalid"


def test_root_record_extensions_keep_the_legacy_payload_and_validate_keys():
    legacy = CatalogRootRecord(
        version=1,
        threshold=1,
        root_key_ids=frozenset({"r"}),
        snapshot_key_ids=frozenset({"s"}),
        timestamp_key_ids=frozenset({"t"}),
        signed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    assert set(json.loads(legacy.canonical_payload())) == {
        "role",
        "version",
        "threshold",
        "root_key_ids",
        "snapshot_key_ids",
        "timestamp_key_ids",
        "signed_at",
        "expires_at",
    }
    key = _key("one")
    with pytest.raises(ValueError, match="cover exactly"):
        replace(legacy, public_keys={_ident(key): _raw(key)})
    named = replace(
        legacy,
        root_key_ids=frozenset({_ident(key)}),
        snapshot_key_ids=frozenset({_ident(key)}),
        timestamp_key_ids=frozenset({_ident(key)}),
    )
    with pytest.raises(ValueError, match="self-certifying"):
        replace(named, public_keys={_ident(key): _raw(_key("two"))})
    assert replace(named, public_keys={_ident(key): _raw(key)}).digest.startswith("sha256:")


def test_snapshot_export_binding_is_optional_and_part_of_the_signed_payload():
    plain = CatalogSnapshotRecord(
        version=1,
        channel_versions={"DEV": 1},
        key_id="k",
        signed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    bound = replace(plain, export_digest="a" * 64, export_revision=7)
    assert "export_digest" not in plain.to_mapping()
    assert bound.canonical_payload() != plain.canonical_payload()
    assert bound.digest != plain.digest
    with pytest.raises(ValueError, match="non-negative"):
        replace(plain, export_revision=-1)


def test_wire_round_trips_are_exact_and_reject_unexpected_fields():
    holders = [_key(f"h-{i}") for i in range(3)]
    root = _root(1, holders, holders[:2])
    assert root_from_wire(json.loads(json.dumps(root_to_wire(root)))) == root
    snapshot = CatalogSnapshotRecord(
        version=2,
        channel_versions={"DEV": 5},
        recall_sequences=(1,),
        release_digests={"1.0.0": "sha256:" + "a" * 64},
        key_id="k",
        signed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        signature=b"s" * 64,
        export_digest="b" * 64,
        export_revision=5,
    )
    assert snapshot_from_wire(snapshot_to_wire(snapshot)) == snapshot
    timestamp = CatalogTimestampRecord(
        version=3,
        snapshot_version=2,
        snapshot_digest=snapshot.digest,
        key_id="t",
        signed_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        signature=b"s" * 64,
    )
    assert timestamp_from_wire(timestamp_to_wire(timestamp)) == timestamp
    for wire, loader in (
        (root_to_wire(root), root_from_wire),
        (snapshot_to_wire(snapshot), snapshot_from_wire),
        (timestamp_to_wire(timestamp), timestamp_from_wire),
    ):
        with pytest.raises(ValueError):
            loader({**wire, "extra": 1})
        with pytest.raises(ValueError):
            loader({**wire, "role": "other"})
        with pytest.raises(ValueError):
            loader({**wire, "signature": b64encode(b"x").decode()} if "signature" in wire else {})
    with pytest.raises(ValueError):
        loader({**timestamp_to_wire(timestamp), "version": True})
