#!/usr/bin/env python3
"""Extract one resolved-model digest from verified Core image attestations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 2 * 1024 * 1024


class ActiveModelAttestationError(RuntimeError):
    """The verified attestation set does not identify one model artifact."""


def active_model_digest(path: Path) -> str:
    """Return the unique canonical resolved-model digest from verified statements."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise ActiveModelAttestationError("active model attestations are unavailable or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActiveModelAttestationError("active model attestations are invalid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise ActiveModelAttestationError("active model attestations MUST be a non-empty array")
    digests: set[str] = set()
    for record in payload:
        if not isinstance(record, dict):
            raise ActiveModelAttestationError("active model attestation record is invalid")
        verification = record.get("verificationResult")
        statement = verification.get("statement") if isinstance(verification, dict) else None
        predicate = statement.get("predicate") if isinstance(statement, dict) else None
        models = predicate.get("resolved_models") if isinstance(predicate, dict) else None
        digest = models.get("canonical_json_sha256") if isinstance(models, dict) else None
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ActiveModelAttestationError("active model attestation digest is invalid")
        digests.add(digest)
    if len(digests) != 1:
        raise ActiveModelAttestationError("active model attestations disagree on the digest")
    return next(iter(digests))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attestations", type=Path, required=True)
    args = parser.parse_args()
    try:
        digest = active_model_digest(args.attestations)
    except ActiveModelAttestationError as exc:
        print(f"active model attestation verification failed: {exc}")
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
