"""The exact VM policy and discovery sources must survive authenticated bundle delivery."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fdai_deployment_cli.bundle import BundleVerificationError, verify_bundle

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/release"))
PATHS = (
    "infra/genesis-runner-image/vm-sku-policy.json",
    "scripts/deployment/azure/genesis_vm_sku_catalog.py",
    "scripts/deployment/azure/genesis_vm_sku_choice.py",
    "scripts/deployment/azure/genesis_vm_sku_policy.py",
    "scripts/deployment/azure/genesis_vm_sku_preflight.py",
    "scripts/deployment/azure/genesis_vm_sku_image.py",
    "scripts/deployment/azure/genesis_vm_image_requirements.py",
)


@pytest.mark.parametrize("tamper", [None, "policy", "source", "extra"])
def test_tracked_vm_sources_are_signed_and_tampering_fails(tmp_path, tamper):
    builder = runpy.run_path(str(ROOT / "scripts/deployment/release/build-deployment-bundle.py"))
    assert set(PATHS) <= set(builder["_tracked_paths"](ROOT))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    bundle = tmp_path / "bundle"
    builder["build_bundle"](
        ROOT,
        bundle,
        source_paths=PATHS,
        bundle_version="0.1.0",
        release_channel="development",
        min_cli_version="0.1.0",
        max_cli_version=None,
        private_key_pem=private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        source_date_epoch=1700000000,
    )
    if tamper == "policy":
        (bundle / PATHS[0]).write_bytes((bundle / PATHS[0]).read_bytes() + b" ")
    elif tamper == "source":
        (bundle / PATHS[1]).unlink()
    elif tamper == "extra":
        (bundle / "unsigned.py").write_text("# unsigned source\n")
    if tamper is not None:
        with pytest.raises(BundleVerificationError):
            verify_bundle(bundle, public_key_pem=public, cli_version="0.1.0")
        return
    verified = verify_bundle(bundle, public_key_pem=public, cli_version="0.1.0")
    assert verified.manifest_digest
    assert all((bundle / name).read_bytes() == (ROOT / name).read_bytes() for name in PATHS)
