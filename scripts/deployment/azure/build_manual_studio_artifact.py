#!/usr/bin/env python3
"""Build the allowlisted Manual Studio artifact for the Console site."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

_ROOT_FILES = (
    "app.js",
    "catalog.json",
    "executive-deck.css",
    "executive-story.css",
    "library.html",
    "manual-content.js",
    "manual-decks.css",
    "styles.css",
)
_ASSET_SUFFIXES = frozenset({".jpeg", ".json", ".png"})


def build_artifact(repo_root: Path, output: Path) -> list[Path]:
    """Copy publishable Manual Studio files into a new output directory."""
    source_root = (repo_root / "tools" / "manual-studio").resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    source_files = [source_root / name for name in _ROOT_FILES]
    assets_root = source_root / "assets"
    source_files.extend(
        path
        for path in sorted(assets_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in _ASSET_SUFFIXES
    )
    for source in source_files:
        if source.is_symlink():
            raise ValueError(f"symlinks are not allowed in the static artifact: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"Manual Studio source file is unavailable: {source}")

    output.mkdir(parents=True)
    copied: list[Path] = []
    for source in source_files:
        destination = output / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[3])
    args = parser.parse_args()
    copied = build_artifact(args.repo_root, args.output)
    print(f"built Manual Studio artifact: {len(copied)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
