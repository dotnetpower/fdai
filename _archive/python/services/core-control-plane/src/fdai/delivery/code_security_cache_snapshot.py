"""Publish immutable vulnerability-cache generations without losing the last good pointer."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.code_security_prepared_source import source_tree_digest

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_POINTER_BYTES = 4096


def publish_cache_snapshot(source: Path, root: Path) -> dict[str, object]:
    """Publish a cache only after its preparation process succeeds.

    The wrapper owns preparation completion. A digest binds bytes, not database freshness or
    package completeness; missing tool metadata remains a scanner coverage limitation.
    """
    if root.resolve().is_relative_to(source.resolve()):
        raise ValueError("cache snapshot output cannot be inside its input")
    digest = source_tree_digest(source)
    if not any(source.iterdir()):
        raise ValueError("cannot publish an empty vulnerability cache")
    generations = root / "snapshots"
    generations.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = generations / digest
    if destination.exists():
        if destination.is_symlink() or source_tree_digest(destination / "cache") != digest:
            raise ValueError("existing cache generation differs from its digest")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=generations))
        try:
            shutil.copytree(source, temporary / "cache", symlinks=True)
            if (
                source_tree_digest(temporary / "cache") != digest
                or source_tree_digest(source) != digest
            ):
                raise ValueError("vulnerability cache changed during snapshot publication")
            for path in (temporary / "cache").rglob("*"):
                mode = path.stat().st_mode
                path.chmod(0o500 if stat.S_ISDIR(mode) else 0o400 | (mode & 0o111))
            (temporary / "cache").chmod(0o500)
            temporary.rename(destination)
        finally:
            if temporary.exists():
                for path in temporary.rglob("*"):
                    if path.is_dir() and not path.is_symlink():
                        path.chmod(0o700)
                shutil.rmtree(temporary)
    pointer = {
        "schema_version": 1,
        "cache_digest": digest,
        "cache_subpath": f"snapshots/{digest}/cache",
        "prepared_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    temporary_pointer = root / ".current.json.tmp"
    temporary_pointer.write_text(json.dumps(pointer, sort_keys=True) + "\n")
    temporary_pointer.chmod(0o600)
    temporary_pointer.replace(root / "current.json")
    return {"ok": True, **pointer}


def resolve_cache_snapshot(root: Path) -> Path:
    """Return the current immutable cache only after validating its pointer and bytes."""
    pointer_path = root / "current.json"
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise ValueError("vulnerability cache pointer is missing")
    if pointer_path.stat().st_size > _MAX_POINTER_BYTES:
        raise ValueError("vulnerability cache pointer exceeds its byte bound")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("vulnerability cache pointer is malformed") from exc
    if not isinstance(pointer, dict) or set(pointer) != {
        "schema_version",
        "cache_digest",
        "cache_subpath",
        "prepared_at",
    }:
        raise ValueError("vulnerability cache pointer has an invalid envelope")
    digest = pointer.get("cache_digest")
    subpath = pointer.get("cache_subpath")
    prepared_at = pointer.get("prepared_at")
    try:
        prepared_time = (
            datetime.fromisoformat(prepared_at) if isinstance(prepared_at, str) else None
        )
    except ValueError as exc:
        raise ValueError("vulnerability cache pointer has invalid fields") from exc
    if (
        pointer.get("schema_version") != 1
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or subpath != f"snapshots/{digest}/cache"
        or prepared_time is None
        or prepared_time.tzinfo is None
    ):
        raise ValueError("vulnerability cache pointer has invalid fields")
    cache = root / subpath
    if cache.is_symlink() or not cache.is_dir():
        raise ValueError("vulnerability cache snapshot is missing")
    if not cache.resolve().is_relative_to(root.resolve()):
        raise ValueError("vulnerability cache snapshot escapes its root")
    if source_tree_digest(cache) != digest:
        raise ValueError("vulnerability cache snapshot digest does not match its pointer")
    return cache


def add_cache_snapshot_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("publish-cache-snapshot", help="publish a prepared immutable cache")
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", required=True)
    resolve = sub.add_parser(
        "resolve-cache-snapshot",
        help="validate and resolve the current immutable vulnerability cache",
    )
    resolve.add_argument("--root", required=True)


def run_publish_cache_snapshot(args: argparse.Namespace) -> dict[str, object]:
    return publish_cache_snapshot(Path(args.path), Path(args.out))


def run_resolve_cache_snapshot(args: argparse.Namespace) -> dict[str, object]:
    cache = resolve_cache_snapshot(Path(args.root))
    return {"ok": True, "cache_path": str(cache)}
