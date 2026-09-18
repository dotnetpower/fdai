#!/usr/bin/env python3
"""Hash service-owned source and private environment inputs without rendering them."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

_CHUNK_BYTES = 1024 * 1024
_DIGEST_IMPLEMENTATION = Path(__file__)
_SUPERVISION_INPUTS = (
    Path(__file__).with_name("run-local-service.sh"),
    Path(__file__).with_name("run-local-service-child.py"),
)


class _Digest(Protocol):
    def update(self, data: bytes) -> None: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="hash only the supplied paths without local service supervision inputs",
    )
    parser.add_argument(
        "--timing-label",
        help="emit a structured, content-free timing event to stderr",
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


def _git_output(root: Path, arguments: list[str]) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _git_material(
    inputs: tuple[Path, ...],
) -> tuple[Path, bytes, bytes, bytes, frozenset[Path]] | None:
    """Return content-sensitive Git material without reading every tracked file."""
    try:
        root = Path(
            os.fsdecode(_git_output(Path.cwd(), ["rev-parse", "--show-toplevel"]).strip())
        ).resolve()
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return None

    pathspecs: list[str] = []
    for supplied in inputs:
        absolute = supplied.absolute()
        try:
            relative = absolute.relative_to(root)
        except ValueError:
            continue
        pathspecs.append(relative.as_posix() or ".")
    if not pathspecs:
        return None

    separator = ["--", *pathspecs]
    try:
        staged = _git_output(root, ["ls-files", "--stage", "-z", *separator])
        modified = _git_output(
            root,
            [
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                *separator,
            ],
        )
        untracked = _git_output(
            root,
            ["ls-files", "--others", "--exclude-standard", "-z", *separator],
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    untracked_records = tuple(
        encoded_path
        for encoded_path in untracked.split(b"\0")
        if encoded_path
        and "__pycache__" not in Path(os.fsdecode(encoded_path)).parts
        and Path(os.fsdecode(encoded_path)).suffix != ".pyc"
    )
    filtered_untracked = b"\0".join(untracked_records)
    if filtered_untracked:
        filtered_untracked += b"\0"
    untracked_paths = frozenset(
        root / os.fsdecode(encoded_path) for encoded_path in untracked_records
    )
    return root, staged, modified, filtered_untracked, untracked_paths


def _update_payload(digest: _Digest, kind: bytes, payload: bytes) -> None:
    digest.update(kind)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _update_file(digest: _Digest, path: Path, label: bytes) -> None:
    _update_payload(digest, b"P", label)
    if path.is_symlink():
        _update_payload(digest, b"L", path.readlink().as_posix().encode())
        return
    digest.update(b"F")
    digest.update(path.stat().st_size.to_bytes(8, "big"))
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)


def _update_files(digest: _Digest, root: Path) -> None:
    for candidate in _files(root):
        relative = candidate.relative_to(root) if root.is_dir() else Path(root.name)
        label = f"{root.as_posix()}\0{relative.as_posix()}".encode()
        _update_file(digest, candidate, label)


def input_digest(inputs: tuple[Path, ...]) -> str:
    """Hash tracked source state, non-ignored additions, and explicit private files."""
    for supplied in inputs:
        if not supplied.exists() and not supplied.is_symlink():
            raise ValueError(f"local service fingerprint input is unavailable: {supplied}")

    digest = hashlib.sha256()
    digest.update(b"fdai-local-input-digest-git-material-v1\0")
    material = _git_material(inputs)
    if material is None:
        for supplied in inputs:
            _update_files(digest, supplied)
        return digest.hexdigest()

    repository_root, staged, modified, untracked, untracked_paths = material
    for supplied in inputs:
        _update_payload(digest, b"R", supplied.as_posix().encode())
    _update_payload(digest, b"I", staged)
    _update_payload(digest, b"D", modified)
    _update_payload(digest, b"U", untracked)

    for path in sorted(untracked_paths):
        _update_file(
            digest,
            path,
            path.relative_to(repository_root).as_posix().encode(),
        )

    for supplied in inputs:
        absolute = supplied.absolute()
        try:
            relative = absolute.relative_to(repository_root)
        except ValueError:
            _update_files(digest, supplied)
            continue
        if (supplied.is_file() or supplied.is_symlink()) and absolute not in untracked_paths:
            encoded_path = os.fsencode(relative)
            if b"\t" + encoded_path + b"\0" not in staged:
                _update_file(digest, supplied, supplied.as_posix().encode())
    return digest.hexdigest()


def main() -> int:
    arguments = _parser().parse_args()
    started_at = time.monotonic_ns()
    inputs = (*arguments.inputs, _DIGEST_IMPLEMENTATION)
    if not arguments.paths_only:
        inputs = (*inputs, *_SUPERVISION_INPUTS)
    try:
        print(input_digest(inputs))
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if arguments.timing_label:
        duration_ms = (time.monotonic_ns() - started_at) // 1_000_000
        print(
            "service=local-input-digest "
            f"stage={arguments.timing_label} event=completed duration_ms={duration_ms}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
