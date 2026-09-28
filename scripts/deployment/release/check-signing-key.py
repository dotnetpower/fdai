#!/usr/bin/env python3
"""Report whether a candidate private key is one of the packaged signing roots.

Key material is never printed, copied, or transmitted. The script reports only a
path, a public-key fingerprint, the roles that key satisfies, and file custody
metadata, so it is safe to run on any machine that may hold the key.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "packages/deployment-cli/src"))

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_pem_public_key,
    )
except ImportError:  # pragma: no cover - dependency guidance only
    sys.exit("check-signing-key: install the 'cryptography' package first")

from fdai_deployment_cli import trust_roots  # noqa: E402 - needs the sys.path entry above

# One candidate key may satisfy several roles, because the development profile
# pins a single signer for both the complete kit and the bundle inside it.
_ROLES: tuple[tuple[str, str], ...] = (
    ("deployment-release", "fdai-up.sh --signing-key / --release-key"),
    ("deployment-bundle", "fdai-up.sh --signing-key / --bundle-key"),
    ("license-issuer", "--license-signing-key"),
)
_MAX_KEY_BYTES = 8192


def expected_roots() -> dict[str, str]:
    """Return each role's expected public-key fingerprint."""

    pems = {
        "deployment-release": trust_roots.deployment_release_root_pem(),
        "deployment-bundle": trust_roots.deployment_bundle_root_pem(),
        "license-issuer": trust_roots.license_public_key_pem(),
    }
    return {role: _fingerprint(_public_bytes(pem)) for role, pem in pems.items()}


def _public_bytes(pem: bytes) -> bytes:
    public = load_pem_public_key(pem)
    if not isinstance(public, Ed25519PublicKey):
        raise ValueError("packaged trust root is not an Ed25519 public key")
    return public.public_bytes_raw()


def _fingerprint(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def key_fingerprint(path: Path) -> str | None:
    """Return the candidate's public fingerprint, or None when it is not usable."""

    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_KEY_BYTES:
            return None
        private = load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(private, Ed25519PrivateKey):
        return None
    return _fingerprint(private.public_key().public_bytes_raw())


def custody_findings(path: Path) -> list[str]:
    """Return the unmet custody requirements the kit build enforces."""

    details = path.lstat()
    findings = []
    if stat.S_IMODE(details.st_mode) != 0o600:
        findings.append(f"mode is {oct(stat.S_IMODE(details.st_mode))[2:]}, must be 600")
    if details.st_uid != os.geteuid():
        findings.append("file is owned by another user")
    if details.st_nlink != 1:
        findings.append(f"file has {details.st_nlink} hard links, must have 1")
    return findings


def _candidates(directory: Path) -> Iterator[Path]:
    for path in sorted(directory.rglob("*.pem")):
        if not path.is_symlink():
            yield path


def _report_expected(roots: dict[str, str]) -> None:
    print("check-signing-key: expected roots")
    for role, fingerprint in roots.items():
        print(f"  {role:<19} {fingerprint}")


def _check_one(path: Path, roots: dict[str, str]) -> int:
    if not path.exists():
        print(f"check-signing-key: {path}: no such file", file=sys.stderr)
        return 2
    fingerprint = key_fingerprint(path)
    if fingerprint is None:
        print(f"check-signing-key: {path}: not a readable Ed25519 private key", file=sys.stderr)
        return 2
    matched = [role for role, expected in roots.items() if expected == fingerprint]
    print(f"check-signing-key: {path}")
    print(f"  fingerprint         {fingerprint}")
    if not matched:
        print("  roles               none")
        print(
            "check-signing-key: NO MATCH - this key is not a packaged signing root.",
            file=sys.stderr,
        )
        return 1
    print(f"  roles               {', '.join(matched)}")
    for finding in custody_findings(path):
        print(f"  custody             {finding}")
    usable = [usage for role, usage in _ROLES if role in matched]
    print(f"check-signing-key: MATCH - use with {'; '.join(sorted(set(usable)))}")
    return 0


def _scan(directory: Path, roots: dict[str, str]) -> int:
    if not directory.is_dir():
        print(f"check-signing-key: {directory}: not a directory", file=sys.stderr)
        return 2
    scanned = 0
    matches = 0
    for path in _candidates(directory):
        fingerprint = key_fingerprint(path)
        if fingerprint is None:
            continue
        scanned += 1
        matched = [role for role, expected in roots.items() if expected == fingerprint]
        if matched:
            matches += 1
            print(f"check-signing-key: MATCH {path} roles={', '.join(matched)}")
    print(f"check-signing-key: scanned={scanned} matches={matches}")
    return 0 if matches else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-signing-key.py",
        description=(
            "Report whether a private key is a packaged FDAI signing root. "
            "Key material is never printed."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--key", type=Path, help="Candidate private key to identify")
    group.add_argument("--scan", type=Path, help="Directory to search for candidate keys")
    arguments = parser.parse_args(argv)

    roots = expected_roots()
    _report_expected(roots)
    if arguments.key is not None:
        return _check_one(arguments.key, roots)
    if arguments.scan is not None:
        return _scan(arguments.scan, roots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
