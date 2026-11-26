"""Composition seam for governed execution backend profiles and adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from fdai.core.execution_backend import (
    ExecutionBackendCoordinator,
    ExecutionBackendKind,
    ExecutionBackendProfileRegistry,
    load_execution_backend_registry,
)
from fdai.shared.providers.execution_backend import (
    ExecutionBackend,
    ExecutionSubmissionLedger,
)

from ._helpers import Container


def load_execution_backend_registry_file(path: Path) -> ExecutionBackendProfileRegistry:
    """Load and validate one server-owned registry document at startup."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("execution backend registry file is unreadable or invalid") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("execution backend registry root MUST be an object")
    return load_execution_backend_registry(raw)


def bind_execution_backends(
    container: Container,
    *,
    profiles: ExecutionBackendProfileRegistry,
    backends: Mapping[ExecutionBackendKind, ExecutionBackend],
    ledger: ExecutionSubmissionLedger,
) -> Container:
    """Return a container with a validated, immutable backend coordinator."""

    bound = set(backends)
    required = {profile.backend_kind for profile in profiles.list()}
    missing = required - bound
    if missing:
        names = ", ".join(sorted(value.value for value in missing))
        raise RuntimeError(f"execution backend adapters are not bound: {names}")
    coordinator = ExecutionBackendCoordinator(
        profiles=profiles,
        backends=backends,
        ledger=ledger,
    )
    return replace(container, execution_backend_coordinator=coordinator)


__all__ = ["bind_execution_backends", "load_execution_backend_registry_file"]
