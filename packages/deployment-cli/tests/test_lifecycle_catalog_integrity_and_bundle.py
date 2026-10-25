"""Tests for signed TUF catalog records and signed upgrade bundle Target Hub import (#2396)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fdai_service_contracts.catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    evaluate_catalog_integrity,
)
from fdai_deployment_cli.lifecycle_plan import SignatureVerifier
from fdai_deployment_cli.lifecycle_upgrade_bundle import (
    SignedConfigurationTransferItem,
    build_signed_upgrade_bundle,
    verify_and_import_upgrade_bundle,
)

NOW = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)


def _key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())


def _verifier(keys: dict[str, Ed25519PublicKey]) -> SignatureVerifier:
    def verify(key_id: str, payload: bytes, signature: bytes) -> bool:
        pub = keys.get(key_id)
        if pub is None:
            return False
        try:
            pub.verify(signature, payload)
            return True
        except InvalidSignature:
            return False

    return verify


def test_signed_root_snapshot_and_timestamp_reject_lower_version_recall_gap_and_demote_on_expiry() -> (
    None
):
    root_k1, root_k2 = _key("root-1"), _key("root-2")
    snap_k = _key("snapshot-1")
    ts_k = _key("timestamp-1")
    keyring = {
        "root-1": root_k1.public_key(),
        "root-2": root_k2.public_key(),
        "snapshot-1": snap_k.public_key(),
        "timestamp-1": ts_k.public_key(),
    }

    unsigned_root = CatalogRootRecord(
        version=2,
        threshold=2,
        root_key_ids=frozenset({"root-1", "root-2"}),
        snapshot_key_ids=frozenset({"snapshot-1"}),
        timestamp_key_ids=frozenset({"timestamp-1"}),
        signed_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )
    root_payload = unsigned_root.canonical_payload()
    root = replace(
        unsigned_root,
        signatures={
            "root-1": root_k1.sign(root_payload),
            "root-2": root_k2.sign(root_payload),
        },
    )

    unsigned_snapshot = CatalogSnapshotRecord(
        version=5,
        channel_versions={"DEV": 5, "RELEASE": 3},
        recall_sequences=(1, 2, 3),
        release_digests={"1.6.0": "a" * 64},
        key_id="snapshot-1",
        signed_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=7),
    )
    snapshot = replace(
        unsigned_snapshot,
        signature=snap_k.sign(unsigned_snapshot.canonical_payload()),
    )

    unsigned_ts = CatalogTimestampRecord(
        version=10,
        snapshot_version=snapshot.version,
        snapshot_digest=snapshot.digest,
        key_id="timestamp-1",
        signed_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    timestamp = replace(unsigned_ts, signature=ts_k.sign(unsigned_ts.canonical_payload()))

    valid = evaluate_catalog_integrity(
        root=root,
        snapshot=snapshot,
        timestamp=timestamp,
        verify_signature=_verifier(keyring),
        trusted_now=NOW,
        minimum_root_version=2,
        minimum_snapshot_version=5,
        minimum_timestamp_version=10,
        previous_max_recall_sequence=3,
    )
    assert valid.allowed
    assert not valid.expired
    assert not valid.demote_operator_overrides_to_shadow
    assert valid.allows_plan_type("upgrade")
    assert valid.allows_plan_type("recall-rolloff")

    # 1. Lower version than previously accepted floor is rejected.
    lower_version = evaluate_catalog_integrity(
        root=root,
        snapshot=snapshot,
        timestamp=timestamp,
        verify_signature=_verifier(keyring),
        trusted_now=NOW,
        minimum_timestamp_version=11,
    )
    assert (lower_version.allowed, lower_version.reason_code) == (
        False,
        "catalog_version_rollback",
    )

    # 2. A recall sequence gap (e.g. (1, 2, 4)) is detected and rejected.
    gapped_unsigned = replace(unsigned_snapshot, recall_sequences=(1, 2, 4))
    gapped_snapshot = replace(
        gapped_unsigned,
        signature=snap_k.sign(gapped_unsigned.canonical_payload()),
    )
    gapped_ts_unsigned = replace(unsigned_ts, snapshot_digest=gapped_snapshot.digest)
    gapped_ts = replace(
        gapped_ts_unsigned,
        signature=ts_k.sign(gapped_ts_unsigned.canonical_payload()),
    )
    gap_decision = evaluate_catalog_integrity(
        root=root,
        snapshot=gapped_snapshot,
        timestamp=gapped_ts,
        verify_signature=_verifier(keyring),
        trusted_now=NOW,
    )
    assert (gap_decision.allowed, gap_decision.reason_code) == (False, "recall_sequence_gap")

    # 3. Expired timestamp allows only recall-rolloff and signals operator-override demotion.
    expired_decision = evaluate_catalog_integrity(
        root=root,
        snapshot=snapshot,
        timestamp=timestamp,
        verify_signature=_verifier(keyring),
        trusted_now=NOW + timedelta(hours=2),
    )
    assert expired_decision.allowed
    assert expired_decision.expired
    assert expired_decision.demote_operator_overrides_to_shadow
    assert expired_decision.alert_code == "catalog_timestamp_expired"
    assert expired_decision.allows_plan_type("recall-rolloff")
    assert not expired_decision.allows_plan_type("upgrade")


def test_upgrade_bundle_target_hub_import_rejects_bad_signature_checksum_mismatch_and_unsigned_config() -> (
    None
):
    vendor_key = _key("vendor-release")
    customer_key = _key("customer-config")
    layer_bytes = b"minimal-oci-layer-bytes"
    layer_digest = f"sha256:{hashlib.sha256(layer_bytes).hexdigest()}"
    config_payload = b'{"revision":1,"values":{"replicas":3}}'
    signed_config = SignedConfigurationTransferItem(
        package_id="cfg-rev-1",
        payload=config_payload,
        signature=customer_key.sign(config_payload),
    )

    bundle = build_signed_upgrade_bundle(
        bundle_id="bundle-0002",
        extends_bundle_id="bundle-0001",
        catalog_export_bytes=b'{"releases":{"1.6.0":{}}}',
        image_layers={layer_digest: layer_bytes},
        sign_checksums=vendor_key.sign,
        configuration_packages=(signed_config,),
    )

    def verify_vendor(payload: bytes, sig: bytes) -> bool:
        try:
            vendor_key.public_key().verify(sig, payload)
            return True
        except InvalidSignature:
            return False

    def verify_customer(payload: bytes, sig: bytes) -> bool:
        try:
            customer_key.public_key().verify(sig, payload)
            return True
        except InvalidSignature:
            return False

    imported = verify_and_import_upgrade_bundle(
        bundle,
        verify_vendor_signature=verify_vendor,
        verify_configuration_signature=verify_customer,
        expected_previous_bundle_id="bundle-0001",
    )
    assert imported.bundle_id == "bundle-0002"
    assert layer_digest in imported.mirror.mirrored_digests
    assert imported.verified_configuration_package_digests == (
        hashlib.sha256(config_payload).hexdigest(),
    )

    # 1. Bad vendor signature on the bundle is rejected.
    bad_sig_bundle = replace(bundle, checksum_signature=customer_key.sign(b"forged"))
    with pytest.raises(ValueError, match="upgrade_bundle_signature_invalid"):
        verify_and_import_upgrade_bundle(
            bad_sig_bundle,
            verify_vendor_signature=verify_vendor,
            verify_configuration_signature=verify_customer,
        )

    # 2. Checksum mismatch (tampered catalog export or layer bytes) is rejected.
    tampered_catalog_bundle = replace(
        bundle,
        catalog_export_bytes=b'{"releases":{"1.6.0":{"tampered":true}}}',
    )
    with pytest.raises(ValueError, match="upgrade_bundle_checksum_mismatch"):
        verify_and_import_upgrade_bundle(
            tampered_catalog_bundle,
            verify_vendor_signature=verify_vendor,
            verify_configuration_signature=verify_customer,
        )

    # 3. Unsigned configuration package on transfer media is rejected.
    unsigned_config_bundle = replace(
        bundle,
        configuration_packages=(
            SignedConfigurationTransferItem(
                package_id="cfg-unsigned",
                payload=config_payload,
                signature=b"",
            ),
        ),
    )
    with pytest.raises(ValueError, match="upgrade_bundle_configuration_package_unsigned"):
        verify_and_import_upgrade_bundle(
            unsigned_config_bundle,
            verify_vendor_signature=verify_vendor,
            verify_configuration_signature=verify_customer,
        )
