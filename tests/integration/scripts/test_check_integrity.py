"""Offline integrity checker: one signing key, so only the manifest shape attests.

The upstream integrity key also signs capability licenses and installation
entitlements. A valid signature over any other FDAI document must therefore
never pass as a framework-surface manifest, in either upstream or fork mode.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "integrity" / "check-integrity.sh"
_BASH = shutil.which("bash") or "bash"
_GIT = shutil.which("git") or "git"
_SURFACE = "services/core-control-plane/src/fdai/core/"
_SURFACE_FILE = f"{_SURFACE}example.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed binary, test-controlled arguments
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey]:
    root = tmp_path / "repo"
    surface_file = root / _SURFACE_FILE
    surface_file.parent.mkdir(parents=True)
    surface_file.write_text("VALUE = 1\n", encoding="utf-8")
    integrity = root / "security" / "integrity"
    integrity.mkdir(parents=True)
    key = Ed25519PrivateKey.generate()
    (integrity / "upstream-signing-key.pub").write_bytes(
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    _git(root, "init", "-q")
    _git(root, "add", ".")
    return root, key


def _sign(root: Path, key: Ed25519PrivateKey, document: bytes) -> None:
    integrity = root / "security" / "integrity"
    (integrity / "manifest.json").write_bytes(document)
    (integrity / "manifest.json.sig").write_text(
        base64.b64encode(key.sign(document)).decode("ascii") + "\n", encoding="ascii"
    )


def _run(root: Path, *, fork: bool = False) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "FDAI_FORK"}
    if fork:
        env["FDAI_FORK"] = "1"
    return subprocess.run(  # noqa: S603 - fixed binary, test-controlled arguments
        [_BASH, str(_SCRIPT)], cwd=root, env=env, capture_output=True, text=True, check=False
    )


def _manifest(root: Path, **override: object) -> bytes:
    digest = hashlib.sha256((root / _SURFACE_FILE).read_bytes()).hexdigest()
    document: dict[str, object] = {
        "version": 1,
        "algorithm": "sha256",
        "generated_at": "2026-10-01T00:00:00Z",
        "surface": [_SURFACE],
        "file_count": 1,
        "files": {_SURFACE_FILE: digest},
    }
    document.update(override)
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical(document: dict[str, object]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


_LICENSE = _canonical(
    {
        "schema_version": "fdai.license.v1",
        "license_id": "lic-test",
        "distribution_id": "fdai-upstream",
        "capability_ids": ["operations.typed-mutation"],
        "not_before": "2026-10-01T00:00:00Z",
        "not_after": "2026-10-31T00:00:00Z",
        "image_digest": None,
        "tenant_binding": None,
    }
)


def test_a_signed_manifest_of_the_surface_passes(repo: tuple[Path, Ed25519PrivateKey]) -> None:
    root, key = repo
    _sign(root, key, _manifest(root))

    result = _run(root)

    assert result.returncode == 0, result.stderr
    assert "signature OK" in result.stdout
    assert "content OK" in result.stdout


@pytest.mark.parametrize("fork", [False, True])
def test_a_signed_license_document_never_attests_the_surface(
    repo: tuple[Path, Ed25519PrivateKey], fork: bool
) -> None:
    root, key = repo
    _sign(root, key, _LICENSE)

    result = _run(root, fork=fork)

    assert result.returncode == 1
    assert "signature OK" in result.stdout
    assert "not an integrity manifest" in result.stderr


@pytest.mark.parametrize(
    "override",
    [
        {"surface": [], "files": {}, "file_count": 0},
        {"file_count": 2},
        {"files": {"README.md": "a" * 64}},
        {"schema_version": "fdai.license.v1"},
        {"version": 2},
    ],
)
def test_a_manifest_with_an_invalid_shape_fails_closed(
    repo: tuple[Path, Ed25519PrivateKey], override: dict[str, object]
) -> None:
    root, key = repo
    _sign(root, key, _manifest(root, **override))

    result = _run(root)

    assert result.returncode == 1
    assert "not an integrity manifest" in result.stderr
