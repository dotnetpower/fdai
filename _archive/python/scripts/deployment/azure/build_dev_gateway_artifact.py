#!/usr/bin/env python3
"""Build the allowlisted development operations gateway source artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

_EXCLUDED_NAMES = frozenset({".funcignore", "README.md"})
_REQUIRED = frozenset({"function_app.py", "gateway.py", "host.json", "requirements.txt"})


def build(source: Path, target: Path) -> tuple[str, ...]:
    """Write a deterministic source ZIP and return its member names."""
    if not source.is_dir():
        raise ValueError(f"gateway source directory is unavailable: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if (
                not path.is_file()
                or path.name in _EXCLUDED_NAMES
                or path.suffix == ".pyc"
                or "__pycache__" in path.parts
            ):
                continue
            archive.write(path, path.relative_to(source).as_posix())
    with ZipFile(target) as archive:
        names = tuple(archive.namelist())
    missing = _REQUIRED.difference(names)
    if missing:
        target.unlink(missing_ok=True)
        raise ValueError(f"gateway source artifact is missing: {sorted(missing)}")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    try:
        build(args.source, args.target)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
