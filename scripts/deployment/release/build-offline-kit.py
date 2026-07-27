#!/usr/bin/env python3
"""Sign one staged FDAI offline deployment kit for disconnected delivery.

Release engineering stages the kit on a connected host: the `fdai` wheel plus
every transitive wheel, the signed deployment bundle, the pinned Terraform
binary and provider mirror, OPA, and the SBOM. This script takes that finished
directory, mints the canonical manifest with
:func:`fdai.deployment_cli.offline_kit.build_offline_kit_manifest`, and writes
the detached Ed25519 signature that `fdaictl provision inspect` verifies on the
disconnected side.

Signing code stays release-only and out of the verification path
(``docs/roadmap/deployment/installable-deployment-cli.md``). Fail-closed
properties:

- The manifest is minted from the staged tree, never from an input list, so it
  cannot attest to absent content or to content the verifier would reject.
- A stale signature is removed before the new manifest is written, so an
  interrupted run leaves an unverifiable kit rather than a plausible one.
- The release private key is read from an operator-held path, never logged and
  never written into the kit; the run ends by re-verifying the written kit
  against the public release root.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from fdai.deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    build_offline_kit_manifest,
    verify_offline_kit,
)


class OfflineKitBuildError(RuntimeError):
    """The offline kit could not be signed safely."""


def sign_offline_kit(
    root: Path,
    *,
    private_key_pem: bytes,
    release_root_pem: bytes,
    kit_version: str,
    cli_version: str,
    bundle_version: str,
    platform_tag: str,
    python_wheel: str,
    deployment_bundle: str,
    terraform_binary: str,
    provider_mirror_prefix: str,
    opa_binary: str,
    sbom_path: str,
) -> str:
    """Write the manifest and detached signature, then re-verify the kit."""
    private_key = _private_key(private_key_pem)
    manifest_bytes = build_offline_kit_manifest(
        root,
        kit_version=kit_version,
        cli_version=cli_version,
        bundle_version=bundle_version,
        platform_tag=platform_tag,
        python_wheel=python_wheel,
        deployment_bundle=deployment_bundle,
        terraform_binary=terraform_binary,
        provider_mirror_prefix=provider_mirror_prefix,
        opa_binary=opa_binary,
        sbom_path=sbom_path,
    )
    signature = private_key.sign(manifest_bytes)
    manifest_path = root / MANIFEST_NAME
    signature_path = root / SIGNATURE_NAME
    if manifest_path.is_symlink() or signature_path.is_symlink():
        raise OfflineKitBuildError("offline kit metadata path MUST NOT be a symlink")
    signature_path.unlink(missing_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    signature_path.write_bytes(signature)
    verification = verify_offline_kit(
        root,
        release_root_pem=release_root_pem,
        cli_version=cli_version,
        platform_tag=platform_tag,
    )
    return verification.to_json()


def _private_key(private_key_pem: bytes) -> Ed25519PrivateKey:
    try:
        key = load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise OfflineKitBuildError("release signing key is not an unencrypted PEM key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise OfflineKitBuildError("release signing key MUST be Ed25519")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--kit-version", required=True)
    parser.add_argument("--cli-version", required=True)
    parser.add_argument("--bundle-version", required=True)
    parser.add_argument("--platform-tag", required=True)
    parser.add_argument("--python-wheel", required=True)
    parser.add_argument("--deployment-bundle", required=True)
    parser.add_argument("--terraform-binary", required=True)
    parser.add_argument("--provider-mirror-prefix", required=True)
    parser.add_argument("--opa-binary", required=True)
    parser.add_argument("--sbom-path", required=True)
    args = parser.parse_args(argv)
    try:
        report = sign_offline_kit(
            args.kit,
            private_key_pem=args.private_key.read_bytes(),
            release_root_pem=args.release_root.read_bytes(),
            kit_version=args.kit_version,
            cli_version=args.cli_version,
            bundle_version=args.bundle_version,
            platform_tag=args.platform_tag,
            python_wheel=args.python_wheel,
            deployment_bundle=args.deployment_bundle,
            terraform_binary=args.terraform_binary,
            provider_mirror_prefix=args.provider_mirror_prefix,
            opa_binary=args.opa_binary,
            sbom_path=args.sbom_path,
        )
    except (OSError, ValueError, OfflineKitBuildError) as exc:
        print(f"offline kit build failed: {exc}", file=sys.stderr)
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
