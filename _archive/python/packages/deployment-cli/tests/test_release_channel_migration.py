from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
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
from fdai_deployment_cli.contracts import canonical_bytes

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "scripts/deployment/release/build-deployment-bundle.py"


@pytest.fixture
def signing(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey, bytes]:
    source = tmp_path / "source"
    (source / "infra").mkdir(parents=True)
    (source / "infra/main.tf").write_text("terraform {}\n", encoding="utf-8")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return source, key, public


def _build(signing: tuple[Path, Ed25519PrivateKey, bytes], tmp_path: Path, channel: str) -> Path:
    source, key, _public = signing
    destination = tmp_path / "bundle"
    sys.path.insert(0, str(BUILDER.parent))
    try:
        builder = runpy.run_path(str(BUILDER))
    finally:
        sys.path.pop(0)
    builder["build_bundle"](
        source,
        destination,
        source_paths=("infra/main.tf",),
        bundle_version="0.1.0",
        release_channel=channel,
        min_cli_version="0.1.0",
        max_cli_version=None,
        private_key_pem=key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        source_date_epoch=1700000000,
    )
    return destination


@pytest.mark.parametrize(
    ("channel", "current"),
    [
        ("DEV", "DEV"),
        ("RELEASE_CANDIDATE", "RELEASE_CANDIDATE"),
        ("RELEASE", "RELEASE"),
        ("development", "DEV"),
        ("beta", "RELEASE_CANDIDATE"),
        ("stable", "RELEASE"),
    ],
)
def test_original_signed_channel_bytes_remain_unchanged(
    tmp_path: Path, signing: tuple[Path, Ed25519PrivateKey, bytes], channel: str, current: str
) -> None:
    bundle = _build(signing, tmp_path, "DEV")
    _source, key, public = signing
    manifest = bundle / "manifest.json"
    payload = json.loads(manifest.read_bytes())
    payload["release_channel"] = channel
    original = canonical_bytes(payload) + b"\n"
    signature = key.sign(original)
    manifest.write_bytes(original)
    (bundle / "manifest.json.sig").write_bytes(signature)
    result = verify_bundle(bundle, public_key_pem=public)
    assert result.release_channel == current
    assert result.manifest_digest == hashlib.sha256(original).hexdigest()
    assert manifest.read_bytes() == original
    assert (bundle / "manifest.json.sig").read_bytes() == signature


@pytest.mark.parametrize("channel", ["development", "beta", "stable", "DEV ", "CUSTOM"])
def test_producer_api_refuses_aliases_before_output(
    tmp_path: Path, signing: tuple[Path, Ed25519PrivateKey, bytes], channel: str
) -> None:
    with pytest.raises(RuntimeError, match="release channel must"):
        _build(signing, tmp_path, channel)
    assert not (tmp_path / "bundle").exists()


def test_channel_mapping_cannot_authenticate_rewritten_bytes(
    tmp_path: Path, signing: tuple[Path, Ed25519PrivateKey, bytes]
) -> None:
    bundle = _build(signing, tmp_path, "DEV")
    manifest = bundle / "manifest.json"
    payload = json.loads(manifest.read_bytes())
    payload["release_channel"] = "development"
    manifest.write_bytes(canonical_bytes(payload) + b"\n")
    with pytest.raises(BundleVerificationError, match="signature"):
        verify_bundle(bundle, public_key_pem=signing[2])


@pytest.mark.parametrize("channel", ["dev", "DEV ", "CUSTOM", ""])
def test_even_authentic_unknown_channels_are_not_silently_admitted(
    tmp_path: Path, signing: tuple[Path, Ed25519PrivateKey, bytes], channel: str
) -> None:
    bundle = _build(signing, tmp_path, "DEV")
    manifest = bundle / "manifest.json"
    payload = json.loads(manifest.read_bytes())
    payload["release_channel"] = channel
    original = canonical_bytes(payload) + b"\n"
    manifest.write_bytes(original)
    (bundle / "manifest.json.sig").write_bytes(signing[1].sign(original))
    with pytest.raises(BundleVerificationError, match="release.channel"):
        verify_bundle(bundle, public_key_pem=signing[2])


@pytest.mark.parametrize("channel", ["DEV", "RELEASE_CANDIDATE", "RELEASE", "development"])
def test_real_producer_and_consumer_processes(
    tmp_path: Path, signing: tuple[Path, Ed25519PrivateKey, bytes], channel: str
) -> None:
    source, key, _public = signing
    for command in (["git", "init", "-q", str(source)], ["git", "-C", str(source), "add", "infra"]):
        subprocess.run(command, check=True, capture_output=True, timeout=10)
    private = tmp_path / "synthetic.key"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    private.chmod(0o600)
    public = tmp_path / "synthetic.pub"
    bundle = tmp_path / "bundle"
    archive = tmp_path / "bundle.tar.gz"
    env = dict(
        os.environ,
        SOURCE_DATE_EPOCH="1700000000",
        PYTHONPATH=os.pathsep.join(
            str(ROOT / path)
            for path in (
                "packages/service-contracts/src",
                "packages/deployment-cli/src",
                "services/core-control-plane/src",
            )
        ),
    )
    produced = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source",
            str(source),
            "--destination",
            str(bundle),
            "--archive",
            str(archive),
            "--private-key",
            str(private),
            "--public-key-output",
            str(public),
            "--bundle-version",
            "0.1.0",
            "--min-cli-version",
            "0.1.0",
            "--release-channel",
            channel,
        ],
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if channel == "development":
        assert produced.returncode != 0
        assert "invalid choice" in produced.stderr
        assert not bundle.exists() and not archive.exists() and not public.exists()
        return
    assert produced.returncode == 0, produced.stderr
    assert json.loads((bundle / "manifest.json").read_bytes())["release_channel"] == channel
    consumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "fdai_deployment_cli",
            "bundle",
            "verify",
            "--bundle",
            str(bundle),
            "--public-key",
            str(public),
            "--output",
            "json",
        ],
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert consumed.returncode == 0, consumed.stderr
    assert json.loads(consumed.stdout)["release_channel"] == channel
