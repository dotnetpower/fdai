#!/usr/bin/env python3
"""Hash service-owned source and private environment inputs without rendering them."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

_CHUNK_BYTES = 1024 * 1024
_DIGEST_IMPLEMENTATION = Path(__file__)
_SUPERVISION_INPUTS = (
    Path(__file__).with_name("run-local-service.sh"),
    Path(__file__).with_name("run-local-service-child.py"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="hash only the supplied paths without local service supervision inputs",
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    return parser


def _files(path: Path) -> tuple[Path, ...]:
    if path.is_file() or path.is_symlink():
        return (path,)
    if not path.is_dir():
        raise ValueError(f"local service fingerprint input is unavailable: {path}")
    return tuple(
        candidate
        for candidate in sorted(path.rglob("*"))
        if (candidate.is_file() or candidate.is_symlink())
        and "__pycache__" not in candidate.parts
        and candidate.suffix != ".pyc"
    )


def input_digest(inputs: tuple[Path, ...]) -> str:
    """Return one deterministic digest for paths and bytes under the supplied inputs."""
    digest = hashlib.sha256()
    for root in inputs:
        if not root.exists() and not root.is_symlink():
            raise ValueError(f"local service fingerprint input is unavailable: {root}")
        for candidate in _files(root):
            relative = candidate.relative_to(root) if root.is_dir() else Path(root.name)
            label = f"{root.as_posix()}\0{relative.as_posix()}".encode()
            digest.update(len(label).to_bytes(8, "big"))
            digest.update(label)
            if candidate.is_symlink():
                payload = candidate.readlink().as_posix().encode()
                digest.update(b"L")
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
                continue
            digest.update(b"F")
            digest.update(candidate.stat().st_size.to_bytes(8, "big"))
            with candidate.open("rb") as handle:
                while chunk := handle.read(_CHUNK_BYTES):
                    digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    arguments = _parser().parse_args()
    inputs = (*arguments.inputs, _DIGEST_IMPLEMENTATION)
    if not arguments.paths_only:
        inputs = (*inputs, *_SUPERVISION_INPUTS)
    try:
        print(input_digest(inputs))
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
