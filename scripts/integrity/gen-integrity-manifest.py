#!/usr/bin/env python3
"""gen-integrity-manifest.py - build the tamper-evident framework-surface manifest.

The manifest is a deterministic JSON document mapping every git-tracked file
under the FDAI framework surface (see scripts/lib/framework-surface.txt) to its
SHA-256 content hash. Upstream signs this manifest with an Ed25519 private key
(scripts/integrity/sign-integrity.sh); a downstream fork verifies it fully OFFLINE with
the committed public key (scripts/integrity/check-integrity.sh).

What this gives you (and what it does not):
  - tamper-EVIDENCE: any edit / addition / deletion under the framework surface
    changes the manifest, so a fork that touches it is detected offline.
  - non-forgeable ATTESTATION: a fork cannot mint a new valid manifest without
    the upstream private key.
  - it is NOT tamper-PROOF: a fork owner can still delete the verifier itself.
    Enforcement of trust belongs to an upstream-controlled gate, not this file.

Usage:
  scripts/integrity/gen-integrity-manifest.py [--out PATH] [--check]

  --out PATH   where to write the manifest (default: security/integrity/manifest.json)
  --check      do not write; exit non-zero if the on-disk manifest is stale
               (used in CI to force a regenerate-and-sign when the surface changes)

Determinism: files are sorted; JSON uses sorted keys, 2-space indent, and a
trailing newline, so re-running on the same tree yields byte-identical output
(except the informational `generated_at`, which `--check` ignores).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_VERSION = 1
DEFAULT_OUT = "security/integrity/manifest.json"
SURFACE_LIST = "scripts/lib/framework-surface.txt"


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def load_surface(root: Path) -> list[str]:
    """Parse the framework-surface list into prefix/exact entries."""
    path = root / SURFACE_LIST
    if not path.is_file():
        sys.exit(f"gen-integrity-manifest: ERROR - missing {SURFACE_LIST}")
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    if not entries:
        sys.exit(f"gen-integrity-manifest: ERROR - {SURFACE_LIST} is empty")
    return entries


def matches_surface(path: str, entries: list[str]) -> bool:
    for entry in entries:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path) -> dict:
    entries = load_surface(root)
    surface_files = sorted(p for p in tracked_files(root) if matches_surface(p, entries))
    if not surface_files:
        sys.exit(
            "gen-integrity-manifest: ERROR - no tracked files matched the "
            "framework surface; refusing to write an empty manifest."
        )
    files: dict[str, str] = {}
    for rel in surface_files:
        abs_path = root / rel
        if not abs_path.is_file():
            # A tracked-but-absent path (e.g. sparse checkout) must fail loudly
            # rather than silently drop from the signed set.
            sys.exit(f"gen-integrity-manifest: ERROR - tracked file missing on disk: {rel}")
        files[rel] = sha256_of(abs_path)
    return {
        "version": MANIFEST_VERSION,
        "algorithm": "sha256",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "surface": entries,
        "file_count": len(files),
        "files": files,
    }


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def strip_volatile(manifest: dict) -> dict:
    """Return a copy without the informational, non-deterministic fields."""
    clone = dict(manifest)
    clone.pop("generated_at", None)
    return clone


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the framework-surface integrity manifest."
    )
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"output path (default: {DEFAULT_OUT})")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the on-disk manifest still matches the tree (CI staleness gate)",
    )
    args = parser.parse_args()

    root = repo_root()
    manifest = build_manifest(root)
    out_path = root / args.out

    if args.check:
        if not out_path.is_file():
            print(
                f"gen-integrity-manifest: STALE - {args.out} does not exist; "
                "run without --check to create it.",
                file=sys.stderr,
            )
            return 1
        try:
            current = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"gen-integrity-manifest: STALE - cannot read {args.out}: {exc}", file=sys.stderr)
            return 1
        if strip_volatile(current) == strip_volatile(manifest):
            print(
                f"gen-integrity-manifest: OK - {args.out} is up to date "
                f"({manifest['file_count']} files)."
            )
            return 0
        print(
            f"gen-integrity-manifest: STALE - {args.out} no longer matches the framework surface.\n"
            "  Regenerate and re-sign:\n"
            f"    scripts/integrity/gen-integrity-manifest.py --out {args.out}\n"
            "    scripts/integrity/sign-integrity.sh",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dumps(manifest), encoding="utf-8")
    print(
        f"gen-integrity-manifest: wrote {args.out} ({manifest['file_count']} files). "
        "Now sign it: scripts/integrity/sign-integrity.sh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
