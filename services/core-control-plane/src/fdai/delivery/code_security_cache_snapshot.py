"""Publish immutable vulnerability-cache generations without losing the last good pointer."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.code_security_prepared_source import source_tree_digest


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


def add_cache_snapshot_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("publish-cache-snapshot", help="publish a prepared immutable cache")
    parser.add_argument("--path", required=True)
    parser.add_argument("--out", required=True)


def run_publish_cache_snapshot(args: argparse.Namespace) -> dict[str, object]:
    return publish_cache_snapshot(Path(args.path), Path(args.out))
