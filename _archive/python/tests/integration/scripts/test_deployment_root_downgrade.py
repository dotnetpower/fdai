"""Regression test for signed deployment-root downgrade protection."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fdai_deployment_cli.offline_kit import (
    ROOT_MANIFEST_NAME,
    ROOT_SIGNATURE_NAME,
    OfflineKitVerificationError,
    verify_offline_kit,
    verify_root_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_new_signed_kit_rejects_stripped_deployment_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = runpy.run_path(str(REPO_ROOT / "packages/deployment-cli/tests/test_artifacts_cli.py"))
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts/deployment/release"))
    signer = runpy.run_path(str(REPO_ROOT / "scripts/deployment/release/build-offline-kit.py"))
    private, public, _manifest = fixture["_kit"](tmp_path)
    sign_offline_kit = signer["sign_offline_kit"]
    sign_offline_kit(
        tmp_path,
        private_key_pem=private.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        ),
        release_root_pem=public,
        kit_version="0.1.0",
        cli_version="0.1.0",
        bundle_version="0.1.0",
        platform_tag="linux-x86_64",
        python_wheel="python/fdai_deployment_cli-0.1.0-py3-none-any.whl",
        deployment_bundle="deployment/bundle.tar.gz",
        terraform_binary="terraform/terraform",
        provider_mirror_prefix="terraform/providers",
        opa_binary="bin/opa",
        sbom_path="sbom/offline-kit.cdx.json",
    )
    root = verify_root_manifest(
        tmp_path,
        release_root_pem=public,
        expected_profile="offline",
    )
    assert root.profiles == ("offline",)
    (tmp_path / ROOT_MANIFEST_NAME).unlink()
    (tmp_path / ROOT_SIGNATURE_NAME).unlink()

    with pytest.raises(OfflineKitVerificationError):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
        )
