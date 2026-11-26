"""Release interruption cannot turn incomplete signing into a verifiable kit."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fdai_deployment_cli.offline_kit import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    OfflineKitVerificationError,
    verify_offline_kit,
)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/release"))


@pytest.mark.parametrize("failed_output", [MANIFEST_NAME, SIGNATURE_NAME])
def test_signing_write_failure_removes_previous_signature(tmp_path, monkeypatch, failed_output):
    fixture = runpy.run_path(str(ROOT / "packages/deployment-cli/tests/test_artifacts_cli.py"))
    signer = runpy.run_path(str(ROOT / "scripts/deployment/release/build-offline-kit.py"))
    private, public, _manifest = fixture["_kit"](tmp_path)
    sign = signer["sign_offline_kit"]
    original = sign.__globals__["write_work_file"]

    def interrupted(path, *args, **kwargs):
        if path.name == failed_output:
            raise OSError("synthetic interrupted metadata write")
        return original(path, *args, **kwargs)

    monkeypatch.setitem(sign.__globals__, "write_work_file", interrupted)
    with pytest.raises(OSError, match="synthetic interrupted"):
        sign(
            tmp_path,
            private_key_pem=private.private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
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
    assert not (tmp_path / SIGNATURE_NAME).exists()
    with pytest.raises(OfflineKitVerificationError):
        verify_offline_kit(
            tmp_path,
            release_root_pem=public,
            cli_version="0.1.0",
            platform_tag="linux-x86_64",
        )
