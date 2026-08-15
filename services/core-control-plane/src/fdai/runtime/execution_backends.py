"""Runtime startup loader for the server-owned execution backend registry document."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from fdai.composition import load_execution_backend_registry_file
from fdai.core.execution_backend import ExecutionBackendProfileRegistry

REGISTRY_PATH_VARIABLE = "FDAI_EXECUTION_BACKEND_REGISTRY_PATH"
REGISTRY_MAX_BYTES_VARIABLE = "FDAI_EXECUTION_BACKEND_REGISTRY_MAX_BYTES"
_DEFAULT_MAX_BYTES = 1024 * 1024


def load_execution_backend_registry_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> ExecutionBackendProfileRegistry | None:
    """Return the validated registry when configured, or `None` when it is absent.

    An unset path leaves the runtime without execution backend profiles, which keeps
    every governed backend unavailable. A configured but unreadable, oversized, or
    invalid document fails startup instead of silently degrading to no profiles.
    """

    values = env if env is not None else os.environ
    raw_path = values.get(REGISTRY_PATH_VARIABLE, "").strip()
    if not raw_path:
        return None
    max_bytes = _max_bytes(values)
    path = Path(raw_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RuntimeError(f"{REGISTRY_PATH_VARIABLE} is unreadable") from exc
    if size > max_bytes:
        raise RuntimeError(f"{REGISTRY_PATH_VARIABLE} exceeds the configured byte bound")
    return load_execution_backend_registry_file(path)


def _max_bytes(values: Mapping[str, str]) -> int:
    raw = values.get(REGISTRY_MAX_BYTES_VARIABLE, "").strip()
    if not raw:
        return _DEFAULT_MAX_BYTES
    try:
        max_bytes = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{REGISTRY_MAX_BYTES_VARIABLE} MUST be an integer") from exc
    if max_bytes <= 0:
        raise RuntimeError(f"{REGISTRY_MAX_BYTES_VARIABLE} MUST be positive")
    return max_bytes


__all__ = [
    "REGISTRY_MAX_BYTES_VARIABLE",
    "REGISTRY_PATH_VARIABLE",
    "load_execution_backend_registry_from_env",
]
