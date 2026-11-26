#!/usr/bin/env python3
"""Copy bounded protected-deployment evidence into one fixed candidate layout."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

_MAX_INPUT_BYTES = 1024 * 1024


class DecisionEvidenceCandidateError(ValueError):
    """A candidate input is unsafe, oversized, or incomplete."""


def prepare_candidate(
    *,
    sources: dict[str, Path],
    container_url: str,
    output: Path,
) -> None:
    """Create one owner-only directory containing the fixed evidence files."""

    expected = {
        "apply-claim.json",
        "apply-receipt.json",
        "azure-preflight-evidence.json",
        "plan-metadata.json",
        "preflight-evidence.json",
    }
    if set(sources) != expected:
        raise DecisionEvidenceCandidateError("decision evidence candidate file set is incomplete")
    normalized_url = _container_url(container_url)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, source in sources.items():
        _write(output / name, _read_bounded(source, name=name))
    _write(
        output / "decision-evidence-container-url.txt",
        (normalized_url + "\n").encode(),
    )


def _container_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(segments) != 1
    ):
        raise DecisionEvidenceCandidateError(
            "decision evidence container URL MUST identify one HTTPS container"
        )
    return normalized


def _write(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _read_bounded(path: Path, *, name: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise DecisionEvidenceCandidateError(f"{name} MUST be a bounded regular file") from exc
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_INPUT_BYTES:
            raise DecisionEvidenceCandidateError(f"{name} MUST be a bounded regular file")
        content = stream.read(_MAX_INPUT_BYTES + 1)
    if len(content) > _MAX_INPUT_BYTES:
        raise DecisionEvidenceCandidateError(f"{name} MUST be a bounded regular file")
    return content


def main() -> int:
    """Parse fixed source paths and create the candidate directory."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-metadata", type=Path, required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--azure-preflight-evidence", type=Path, required=True)
    parser.add_argument("--apply-claim", type=Path, required=True)
    parser.add_argument("--apply-receipt", type=Path, required=True)
    parser.add_argument("--container-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_candidate(
            sources={
                "plan-metadata.json": args.plan_metadata,
                "preflight-evidence.json": args.preflight_evidence,
                "azure-preflight-evidence.json": args.azure_preflight_evidence,
                "apply-claim.json": args.apply_claim,
                "apply-receipt.json": args.apply_receipt,
            },
            container_url=args.container_url,
            output=args.output,
        )
    except (OSError, DecisionEvidenceCandidateError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DecisionEvidenceCandidateError", "prepare_candidate"]
