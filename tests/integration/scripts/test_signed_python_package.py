from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "scripts/deployment/release/build-signed-python-package.sh"


def _executable(path: Path, content: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + content, encoding="utf-8")
    path.chmod(0o755)


def test_signed_python_package_has_one_signature_boundary() -> None:
    source = BUILDER.read_text(encoding="utf-8")

    assert "SHA256SUMS.sig" in source
    assert "python -m pip install --no-index --find-links wheels" in source
    assert "deployment-root" not in source
    assert "sbom" not in source.casefold()
    assert "provenance" not in source.casefold()
    assert "bundle-key" not in source


def test_builder_emits_a_standard_verifiable_wheelhouse(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    openssl = shutil.which("openssl")
    sha256sum = shutil.which("sha256sum")
    assert bash is not None
    assert openssl is not None
    assert sha256sum is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin / "uv",
        """
command="$1"
shift
case "$command" in
  lock)
    exit 0
    ;;
  build)
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--out-dir" ]]; then
        mkdir -p "$2"
        printf 'primary-wheel' >"$2/fdai_deployment_cli-0.1.1-py3-none-any.whl"
        exit 0
      fi
      shift
    done
    ;;
  export)
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--output-file" ]]; then
        printf 'dependency==1.0 --hash=sha256:%064d\\n' 0 >"$2"
        exit 0
      fi
      shift
    done
    ;;
  run)
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--dest" ]]; then
        mkdir -p "$2"
        printf 'dependency-wheel' >"$2/dependency-1.0-py3-none-any.whl"
        exit 0
      fi
      shift
    done
    ;;
esac
exit 2
""",
    )
    key = tmp_path / "signing-key.pem"
    key.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    output = tmp_path / "release"
    completed = subprocess.run(  # noqa: S603 - fixed repository builder and arguments.
        [bash, str(BUILDER), "--out", str(output), "--signing-key", str(key)],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    package = output / "package"
    verified = subprocess.run(  # noqa: S603 - resolved local OpenSSL executable.
        [
            openssl,
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(output / "signer.pub"),
            "-rawin",
            "-in",
            str(package / "SHA256SUMS"),
            "-sigfile",
            str(package / "SHA256SUMS.sig"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    checksums = subprocess.run(  # noqa: S603 - resolved local checksum executable.
        [sha256sum, "-c", "SHA256SUMS"],
        cwd=package,
        check=False,
        capture_output=True,
        text=True,
    )

    assert verified.returncode == 0, verified.stderr
    assert checksums.returncode == 0, checksums.stderr
    assert (package / "requirements.txt").read_text(encoding="utf-8") == (
        "fdai-deployment-cli==0.1.1\n"
    )
    assert sorted(path.name for path in (package / "wheels").glob("*.whl")) == [
        "dependency-1.0-py3-none-any.whl",
        "fdai_deployment_cli-0.1.1-py3-none-any.whl",
    ]
