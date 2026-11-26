"""Signed offline upgrade bundle builder and Target Hub import verifier."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_promotion import BoundaryRegistryMirror

_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class SignedConfigurationTransferItem:
    """Customer-authored signed configuration package carried alongside an upgrade bundle."""

    package_id: str
    payload: bytes
    signature: bytes

    def __post_init__(self) -> None:
        if not self.package_id.strip():
            raise ValueError("package_id MUST NOT be empty")
        if not self.payload:
            raise ValueError("payload MUST NOT be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class SignedUpgradeBundle:
    """Offline upgrade bundle carrying catalog metadata, minimal image layers, and checksums."""

    bundle_id: str
    extends_bundle_id: str | None
    catalog_export_bytes: bytes
    image_layers: Mapping[str, bytes] = field(default_factory=dict)
    checksums: Mapping[str, str] = field(default_factory=dict)
    checksum_signature: bytes = b""
    configuration_packages: tuple[SignedConfigurationTransferItem, ...] = ()

    def __post_init__(self) -> None:
        if not self.bundle_id.strip():
            raise ValueError("bundle_id MUST NOT be empty")
        if not self.catalog_export_bytes:
            raise ValueError("catalog_export_bytes MUST NOT be empty")
        for digest in self.image_layers:
            if _IMAGE_DIGEST.fullmatch(digest) is None:
                raise ValueError("image_layers keys MUST be sha256:<64 hex> digests")

    def canonical_checksum_payload(self) -> bytes:
        return canonical_bytes(
            {
                "schema_version": "fdai.upgrade-bundle-checksums.v1",
                "bundle_id": self.bundle_id,
                "extends_bundle_id": self.extends_bundle_id,
                "checksums": dict(sorted(self.checksums.items())),
            }
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpgradeBundleImportResult:
    """Verified Target Hub import result for one signed upgrade bundle."""

    bundle_id: str
    extends_bundle_id: str | None
    catalog_export_sha256: str
    mirror: BoundaryRegistryMirror
    verified_configuration_package_digests: tuple[str, ...]


def compute_upgrade_bundle_checksums(
    *,
    catalog_export_bytes: bytes,
    image_layers: Mapping[str, bytes],
) -> dict[str, str]:
    """Compute the canonical checksum map for a catalog export and minimal image layers."""

    checksums: dict[str, str] = {
        "catalog_export": hashlib.sha256(catalog_export_bytes).hexdigest(),
    }
    for digest, layer_bytes in sorted(image_layers.items()):
        if _IMAGE_DIGEST.fullmatch(digest) is None:
            raise ValueError("image_layers keys MUST be sha256:<64 hex> digests")
        checksums[f"layer:{digest}"] = hashlib.sha256(layer_bytes).hexdigest()
    return checksums


def build_signed_upgrade_bundle(
    *,
    bundle_id: str,
    extends_bundle_id: str | None,
    catalog_export_bytes: bytes,
    image_layers: Mapping[str, bytes],
    sign_checksums: Callable[[bytes], bytes],
    configuration_packages: tuple[SignedConfigurationTransferItem, ...] = (),
) -> SignedUpgradeBundle:
    """Build and sign an offline upgrade bundle."""

    checksums = compute_upgrade_bundle_checksums(
        catalog_export_bytes=catalog_export_bytes,
        image_layers=image_layers,
    )
    unsigned = SignedUpgradeBundle(
        bundle_id=bundle_id,
        extends_bundle_id=extends_bundle_id,
        catalog_export_bytes=catalog_export_bytes,
        image_layers=dict(image_layers),
        checksums=checksums,
        configuration_packages=configuration_packages,
    )
    signature = sign_checksums(unsigned.canonical_checksum_payload())
    return SignedUpgradeBundle(
        bundle_id=bundle_id,
        extends_bundle_id=extends_bundle_id,
        catalog_export_bytes=catalog_export_bytes,
        image_layers=dict(image_layers),
        checksums=checksums,
        checksum_signature=signature,
        configuration_packages=configuration_packages,
    )


def verify_and_import_upgrade_bundle(
    bundle: SignedUpgradeBundle,
    *,
    verify_vendor_signature: Callable[[bytes, bytes], bool],
    verify_configuration_signature: Callable[[bytes, bytes], bool] | None = None,
    mirror: BoundaryRegistryMirror | None = None,
    expected_previous_bundle_id: str | None = None,
) -> UpgradeBundleImportResult:
    """Verify the vendor checksum signature, every checksum, and each configuration signature."""

    if expected_previous_bundle_id is not None and (
        bundle.extends_bundle_id != expected_previous_bundle_id
    ):
        raise ValueError("upgrade_bundle_lineage_mismatch")
    if not bundle.checksum_signature or not bool(
        verify_vendor_signature(bundle.canonical_checksum_payload(), bundle.checksum_signature)
    ):
        raise ValueError("upgrade_bundle_signature_invalid")

    expected_checksums = compute_upgrade_bundle_checksums(
        catalog_export_bytes=bundle.catalog_export_bytes,
        image_layers=bundle.image_layers,
    )
    if dict(bundle.checksums) != expected_checksums:
        raise ValueError("upgrade_bundle_checksum_mismatch")
    for digest, layer_bytes in bundle.image_layers.items():
        actual_layer_digest = f"sha256:{hashlib.sha256(layer_bytes).hexdigest()}"
        if actual_layer_digest != digest:
            raise ValueError("upgrade_bundle_checksum_mismatch")

    verified_config_digests: list[str] = []
    for item in bundle.configuration_packages:
        if not item.signature:
            raise ValueError("upgrade_bundle_configuration_package_unsigned")
        if verify_configuration_signature is None or not bool(
            verify_configuration_signature(item.payload, item.signature)
        ):
            raise ValueError("upgrade_bundle_configuration_package_signature_invalid")
        verified_config_digests.append(hashlib.sha256(item.payload).hexdigest())

    current_mirror = mirror or BoundaryRegistryMirror()
    updated_mirror = BoundaryRegistryMirror(
        mirrored_digests=current_mirror.mirrored_digests | frozenset(bundle.image_layers.keys())
    )
    return UpgradeBundleImportResult(
        bundle_id=bundle.bundle_id,
        extends_bundle_id=bundle.extends_bundle_id,
        catalog_export_sha256=expected_checksums["catalog_export"],
        mirror=updated_mirror,
        verified_configuration_package_digests=tuple(verified_config_digests),
    )
