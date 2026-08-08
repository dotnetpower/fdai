"""Digest validation inputs reused by local push gates."""

from __future__ import annotations

import hashlib
from pathlib import Path

STRUCTURAL_GATE_INPUTS = (
    "scripts/automation/run-pre-push-structural-gates.sh",
    "scripts/quality/architecture/check-agents-imports.sh",
    "scripts/quality/architecture/check-design-routes.py",
    "scripts/quality/architecture/check-evaluation-boundaries.py",
    "scripts/quality/architecture/check-fork-runtime-independence.py",
    "scripts/quality/architecture/check-file-loc.sh",
    "scripts/quality/architecture/check-independent-services.py",
    "scripts/quality/architecture/check-operator-api-boundaries.py",
    "scripts/quality/architecture/check-subsystem-fanout.sh",
    "scripts/quality/repository/check-doc-links.sh",
    "pyproject.toml",
    "uv.lock",
)


def structural_gate_digest(root: Path) -> str:
    """Digest the shared structural runner, gates, and locked tool inputs."""
    digest = hashlib.sha256()
    for relative in STRUCTURAL_GATE_INPUTS:
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()
