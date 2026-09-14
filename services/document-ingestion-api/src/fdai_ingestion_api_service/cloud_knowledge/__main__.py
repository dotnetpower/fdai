"""Offline knowledge package inspection/assembly; no private key or network input."""

import argparse
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from fdai_service_contracts.cloud_knowledge import SourceRegistryRevision
from fdai_service_contracts.cloud_knowledge_package import (
    MAX_PACKAGE_BYTES,
    KnowledgeTrustPolicy,
    assemble_signed_release,
    verify_package,
)
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseManifest


def _read(path: str, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("input must be a bounded regular file")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("input exceeds its byte limit")
    return content


def main(argv: list[str] | None = None) -> int:
    """Inspect a package or assemble a detached signature, never sign, import, or activate it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "assemble"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--trust", required=True)
    parser.add_argument("--signature")
    parser.add_argument("--key-id")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        registry = SourceRegistryRevision.model_validate_json(_read(args.registry, 1024 * 1024))
        trust = KnowledgeTrustPolicy.model_validate_json(_read(args.trust, 1024 * 1024))
        content = _read(args.input, MAX_PACKAGE_BYTES)
        if args.operation == "assemble":
            if not args.signature or not args.key_id or not args.output:
                raise ValueError("assembly requires detached signature, key id, and new output")
            manifest = KnowledgeReleaseManifest.model_validate_json(content)
            content = assemble_signed_release(
                manifest, key_id=args.key_id, signature=_read(args.signature, 64)
            )
        verified = verify_package(content, registry=registry, trust=trust, now=datetime.now(tz=UTC))
        if args.operation == "assemble":
            descriptor = os.open(Path(args.output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        print(
            json.dumps(
                {
                    "status": "verified_candidate",
                    "release_id": verified.manifest.release_id,
                    "manifest_digest": verified.manifest.digest,
                    "approval_required": True,
                }
            )
        )
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "rejected", "reason": "invalid_package_or_trust_inputs"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
