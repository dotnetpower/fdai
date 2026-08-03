#!/usr/bin/env python3
"""Build the allowlisted static artifact for the design-mocks site."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

_ALLOWED_SUFFIXES = frozenset({".css", ".html", ".js", ".json", ".jsonl", ".svg"})
_SOURCE_DIRECTORIES = (
    Path("mocks"),
    Path("examples"),
    Path("console/public/agent-icons"),
)
_HOSTING_FILES = {
    "403.html": "403.html",
    "staticwebapp.config.json": "staticwebapp.config.json",
}


def build_artifact(repo_root: Path, output: Path) -> list[Path]:
    repo_root = repo_root.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    source_files = [repo_root / "index.html"]
    for relative_directory in _SOURCE_DIRECTORIES:
        directory = repo_root / relative_directory
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symlinks are not allowed in the static artifact: {path}")
            if path.is_file() and path.suffix.lower() in _ALLOWED_SUFFIXES:
                source_files.append(path)

    hosting_root = Path(__file__).with_name("design-mocks")
    output.mkdir(parents=True)
    copied: list[Path] = []
    for source in source_files:
        destination = output / source.relative_to(repo_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    for source_name, destination_name in _HOSTING_FILES.items():
        destination = output / destination_name
        shutil.copy2(hosting_root / source_name, destination)
        copied.append(destination)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[3])
    args = parser.parse_args()
    copied = build_artifact(args.repo_root, args.output)
    print(f"built design-mocks artifact: {len(copied)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
