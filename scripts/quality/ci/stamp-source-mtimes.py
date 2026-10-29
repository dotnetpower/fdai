#!/usr/bin/env python3
"""Prepare bytecode caching without reusing stale code or another checkout's filenames.

Pytest's rewritten bytecode retains absolute code filenames. Cache identity therefore binds the
workspace, Python bytecode format, pytest, and configuration. Full source digests in the cached
manifest invalidate changed files even when their timestamp's truncated hash collides.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_STAMP_BITS = 32
_MANIFEST = Path(".fdai/ci-bytecode-sources.json")
_SCHEMA = 2


def stamps(index_listing: str) -> dict[str, int]:
    """Map each regular file in ``git ls-files -s`` output to its content-derived mtime."""
    result: dict[str, int] = {}
    for line in index_listing.splitlines():
        metadata, _, path = line.partition("\t")
        fields = metadata.split()
        if len(fields) != 3 or fields[0] not in {"100644", "100755"}:
            continue
        # Stay inside the 32-bit range pyc headers store, and above zero.
        result[path] = (int(fields[1][: _STAMP_BITS // 4], 16) & 0x7FFFFFFF) or 1
    return result


def source_digests(root: Path) -> dict[str, str]:
    listing = subprocess.run(  # noqa: S603 - fixed Git plumbing command
        ["git", "ls-files", "-s", "-z", "--", "*.py"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    algorithm = subprocess.run(  # noqa: S603 - fixed Git plumbing command
        ["git", "rev-parse", "--show-object-format"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result: dict[str, str] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, expected, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise ValueError("unmerged Python source cannot use bytecode caching")
        if mode not in {"100644", "100755"}:
            continue
        relative = os.fsdecode(raw_path)
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"tracked Python source is missing or not regular: {relative}")
        data = path.read_bytes()
        actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data)
        if actual.hexdigest() != expected:
            raise ValueError(f"Python source differs from the index: {relative}")
        result[relative] = expected
    return result


def cache_identity(root: Path) -> str:
    inputs = {
        "schema": _SCHEMA,
        "workspace": str(root.resolve()),
        "python": sys.version,
        "magic": importlib.util.MAGIC_NUMBER.hex(),
        "pytest": importlib.metadata.version("pytest"),
        "configuration": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("uv.lock", "pyproject.toml", "scripts/quality/ci/stamp-source-mtimes.py")
            if (root / name).is_file()
        },
    }
    return (
        f"bytecode-v{_SCHEMA}-"
        + hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    )


def validate_restored_cache(root: Path, sources: dict[str, str], identity: str) -> None:
    manifest = root / _MANIFEST
    previous: dict[str, str] = {}
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as error:
            print(f"bytecode-cache: invalid manifest; discarding cache ({type(error).__name__})")
        else:
            if (
                isinstance(payload, dict)
                and payload.get("identity") == identity
                and isinstance(payload.get("sources"), dict)
                and all(
                    isinstance(name, str) and isinstance(digest, str)
                    for name, digest in payload["sources"].items()
                )
            ):
                previous = payload["sources"]
            else:
                print("bytecode-cache: incompatible manifest; discarding cache")
    invalidated = 0
    for directory, children, names in os.walk(root):
        children[:] = [
            name for name in children if not name.startswith(".") and name != "node_modules"
        ]
        if Path(directory).name != "__pycache__":
            continue
        for name in names:
            if not name.endswith(".pyc"):
                continue
            source = (Path(directory).parent / (name.split(".", 1)[0] + ".py")).relative_to(root)
            digest = sources.get(source.as_posix())
            if digest is None or previous.get(source.as_posix()) != digest:
                (Path(directory) / name).unlink()
                invalidated += 1
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"identity": identity, "sources": sources}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"bytecode-cache: invalidated={invalidated}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--validate-restored", action="store_true")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    try:
        sources = source_digests(root)
        identity = cache_identity(root)
        if arguments.validate_restored:
            validate_restored_cache(root, sources, identity)
        else:
            for relative, digest in sources.items():
                path = root / relative
                mtime = (int(digest[: _STAMP_BITS // 4], 16) & 0x7FFFFFFF) or 1
                os.utime(path, (mtime, mtime))
        if arguments.github_output:
            with arguments.github_output.open("a", encoding="utf-8") as output:
                output.write(f"key={identity}\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"bytecode-cache: refused: {error}", file=sys.stderr)
        return 1
    print(f"verified {len(sources)} indexed Python sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
