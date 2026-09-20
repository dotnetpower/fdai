"""Stage one digest-pinned projected Secret generation for the non-root observer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.kubernetes_connector_runtime import private_file

MATERIAL_FILES = ("config.json", "registrations.json", "ca.pem", "client.pem", "client.key")


def material_digest(contents: dict[str, bytes]) -> str:
    """Bind every required byte without returning any credential content."""
    if set(contents) != set(MATERIAL_FILES):
        raise ValueError("connector material file set is invalid")
    return canonical_digest(
        {name: "sha256:" + hashlib.sha256(contents[name]).hexdigest() for name in MATERIAL_FILES}
    )


def stage_connector_material(source: Path, destination: Path, *, expected_digest: str) -> bool:
    """Atomically stage a single projected generation; a replay must be byte-identical.

    Source files may be Kubernetes-managed symlinks inside the read-only mount. Only one resolved
    parent generation, regular single-link files, owner/group read bits and bounded bytes are
    accepted. No source credential bytes or derived configuration are printed.
    """
    root = source.resolve(strict=True)
    if not root.is_dir() or not destination.is_absolute():
        raise ValueError("connector material roots are invalid")
    resolved = {name: (root / name).resolve(strict=True) for name in MATERIAL_FILES}
    if (
        any(not path.is_relative_to(root) for path in resolved.values())
        or len({path.parent for path in resolved.values()}) != 1
    ):
        raise ValueError("connector material must use one in-volume generation")
    contents: dict[str, bytes] = {}
    for name, path in resolved.items():
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & ~0o440
                or info.st_size > 131072
            ):
                raise ValueError("connector projected material must be bounded and read-only")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                content = stream.read(131073)
            if len(content) > 131072:
                raise ValueError("connector projected material exceeds its limit")
            contents[name] = content
        finally:
            os.close(descriptor)
    if material_digest(contents) != expected_digest:
        raise ValueError("connector projected material differs from the reviewed digest")
    if destination.exists() or destination.is_symlink():
        info = destination.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or set(path.name for path in destination.iterdir()) != set(MATERIAL_FILES)
        ):
            raise ValueError("connector private material directory is invalid")
        if (
            material_digest({name: private_file(destination / name) for name in MATERIAL_FILES})
            != expected_digest
        ):
            raise ValueError("connector private material cannot be replaced implicitly")
        return False
    temporary = Path(tempfile.mkdtemp(prefix=".connector-material-", dir=destination.parent))
    try:
        for name, content in contents.items():
            descriptor = os.open(
                temporary / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(temporary, destination)
        return True
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-digest", required=True)
    args = parser.parse_args()
    try:
        changed = stage_connector_material(
            args.source, args.destination, expected_digest=args.expected_digest
        )
        print(json.dumps({"status": "staged" if changed else "unchanged"}))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "unavailable", "reason": "connector_material_rejected"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
