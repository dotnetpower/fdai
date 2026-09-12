"""Digest validation inputs reused by local push gates."""

from __future__ import annotations

import hashlib
from pathlib import Path

STRUCTURAL_GATE_INPUTS = (
    "scripts/automation/run-pre-push-structural-gates.sh",
    "scripts/automation/local_validation_cache.py",
    "scripts/automation/local_validation_inputs.py",
    "scripts/quality/architecture/check-agents-imports.sh",
    "scripts/quality/architecture/check-design-routes.py",
    "scripts/quality/architecture/check-evaluation-boundaries.py",
    "scripts/quality/architecture/check-fork-runtime-independence.py",
    "scripts/quality/architecture/check-file-loc.sh",
    "scripts/quality/architecture/check-independent-services.py",
    "scripts/quality/architecture/check-operator-api-boundaries.py",
    "scripts/quality/architecture/check-subsystem-fanout.sh",
    "scripts/quality/architecture/check-venue-capability-contract.py",
    "scripts/quality/repository/check-doc-links.sh",
    "pyproject.toml",
    "uv.lock",
)


def structural_gate_digest(root: Path) -> str:
    """Digest every runner/checker input plus the complete tracked source tree.

    This queue diagnostic is not the structural reuse key: the local runner also
    verifies installed dependencies, tools and its controlled execution context.
    """
    import subprocess

    digest = hashlib.sha256()
    files = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=root,
        timeout=60,
    ).split(b"\0")
    for relative_bytes in sorted(files):
        if not relative_bytes:
            continue
        path = root / relative_bytes.decode()
        digest.update(relative_bytes + b"\0")
        if path.is_symlink():
            digest.update(str(path.readlink()).encode())
        else:
            digest.update(path.read_bytes())
    for relative in STRUCTURAL_GATE_INPUTS:
        path = root / relative
        digest.update(relative.encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()
