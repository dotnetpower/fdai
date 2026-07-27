#!/usr/bin/env python3
"""Issue one signed capability license for a downstream distribution.

The runtime image carries only the **public** verification key, so entitlement
has to arrive as a separate signed token. This script mints that token: it
builds the canonical claims document, signs it with an operator-held Ed25519
private key, and re-verifies the result against the matching public key before
printing anything.

Fail-closed properties:

- The private key is read from an operator-held path and never printed, logged,
  or written next to the token.
- The token is emitted only after it verifies against the supplied public key,
  so a rotated or mismatched key produces no shippable artifact.
- Claims are validated by the same core contract the runtime uses, so a token
  that the runtime would reject cannot be issued.
- Tenant binding is a digest computed by the caller; this script never accepts
  or stores a raw tenant identifier.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from fdai.core.licensing import (
    LicenseClaims,
    LicenseTokenError,
    encode_license_token,
)
from fdai.core.licensing.token import parse_license_token
from fdai.delivery.trust.ed25519 import Ed25519LicenseVerifier


class LicenseIssueError(RuntimeError):
    """The license could not be issued safely."""


def issue_license(
    *,
    private_key_pem: bytes,
    public_key_pem: bytes,
    license_id: str,
    distribution_id: str,
    capability_ids: tuple[str, ...],
    valid_days: int,
    not_before: datetime,
    image_digest: str | None = None,
    tenant_binding: str | None = None,
) -> str:
    """Return one signed license token that verifies against the public key."""
    if valid_days < 1:
        raise LicenseIssueError("valid_days MUST be at least 1")
    private_key = _private_key(private_key_pem)
    claims = LicenseClaims(
        license_id=license_id,
        distribution_id=distribution_id,
        capability_ids=capability_ids,
        not_before=not_before,
        not_after=not_before + timedelta(days=valid_days),
        image_digest=image_digest,
        tenant_binding=tenant_binding,
    )
    document = claims.canonical_document()
    token = encode_license_token(document, private_key.sign(document))
    _confirm(token, public_key_pem)
    return token


def _confirm(token: str, public_key_pem: bytes) -> None:
    try:
        _claims, document, signature = parse_license_token(token)
    except LicenseTokenError as exc:
        raise LicenseIssueError(f"issued license is not parseable: {exc}") from exc
    if not Ed25519LicenseVerifier(public_key_pem=public_key_pem).verify(document, signature):
        raise LicenseIssueError(
            "issued license does not verify against the supplied public key; "
            "the signing key and the packaged key do not match"
        )


def _private_key(private_key_pem: bytes) -> Ed25519PrivateKey:
    try:
        key = load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise LicenseIssueError("license signing key is not an unencrypted PEM key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseIssueError("license signing key MUST be Ed25519")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--license-id", required=True)
    parser.add_argument("--distribution-id", required=True)
    parser.add_argument("--capability", action="append", required=True, dest="capabilities")
    parser.add_argument("--valid-days", type=int, default=365)
    parser.add_argument("--image-digest", default=None)
    parser.add_argument("--tenant-binding", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        token = issue_license(
            private_key_pem=args.private_key.read_bytes(),
            public_key_pem=args.public_key.read_bytes(),
            license_id=args.license_id,
            distribution_id=args.distribution_id,
            capability_ids=tuple(args.capabilities),
            valid_days=args.valid_days,
            not_before=datetime.now(UTC),
            image_digest=args.image_digest,
            tenant_binding=args.tenant_binding,
        )
    except (OSError, ValueError, LicenseIssueError) as exc:
        print(f"license issue failed: {exc}", file=sys.stderr)
        return 1
    if args.output is None:
        print(token)
    else:
        try:
            _write_private_text(args.output, token + "\n")
        except OSError as exc:
            print(f"license issue failed: {exc}", file=sys.stderr)
            return 1
    return 0


def _write_private_text(path: Path, content: str) -> None:
    """Write the token readable only by its owner, and never through a link.

    A license token is a bearer credential. One issued without an image digest
    or a deployment binding is usable by anyone who can read it, and the
    default file mode leaves it readable by every account on the host that
    issued it. Creating the file with O_NOFOLLOW also stops a link planted at
    the output path from placing the token somewhere the operator did not
    choose.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(content)
    path.chmod(0o600)


if __name__ == "__main__":
    raise SystemExit(main())
