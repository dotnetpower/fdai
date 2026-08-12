"""Build cache-safe environment context for centralized validation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from scripts.automation.validation_queue_support import QueuePaths, atomic_write

_REPOSITORY_LOCAL_GIT_ENV = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_INTERNAL_SUPER_PREFIX",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)


def _available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _recommended_workers() -> str:
    cpu_count = os.cpu_count() or 2
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = float(cpu_count)
    available_memory = _available_memory_bytes()
    if load >= cpu_count or (available_memory and available_memory < 4 * 1024**3):
        workers = 1
    elif load <= cpu_count / 2 and available_memory >= 8 * 1024**3:
        workers = max(2, min(4, cpu_count // 2))
    else:
        workers = 2
    if os.environ.get("FDAI_VALIDATION_BACKGROUND") == "1":
        workers = min(workers, 2)
    return str(workers)


def validation_environment(paths: QueuePaths) -> dict[str, str]:
    """Build the isolated process environment with a bounded worker cap."""
    cache_root = paths.state_root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for variable in _REPOSITORY_LOCAL_GIT_ENV:
        environment.pop(variable, None)
    environment.setdefault("FDAI_PYTEST_MAX_WORKERS", _recommended_workers())
    environment.setdefault("MYPY_CACHE_DIR", str(cache_root / "mypy"))
    environment.setdefault("RUFF_CACHE_DIR", str(cache_root / "ruff"))
    environment["UV_PROJECT_ENVIRONMENT"] = str(paths.state_root / "venv")
    primary_python = paths.repo_root / ".venv" / "bin" / "python"
    environment["UV_PYTHON"] = str(primary_python) if primary_python.is_file() else "3.13"
    environment["FDAI_VALIDATION_ACTIVE"] = "1"
    return environment


def sync_fingerprint(root: Path, environment: dict[str, str]) -> str:
    """Digest every input that controls the reusable Python environment."""
    digest = hashlib.sha256()
    for relative in ("pyproject.toml", "uv.lock"):
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    digest.update(environment["UV_PYTHON"].encode())
    digest.update(b"--frozen --extra dev --extra azure-mcp")
    return digest.hexdigest()


def local_input_digest(root: Path) -> str:
    """Digest ignored local inputs that can affect selected validation."""
    digest = hashlib.sha256()
    for relative in ("resolved-models.json", "resolved-models-local.json"):
        path = root / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def sync_is_current(paths: QueuePaths, fingerprint: str) -> bool:
    """Return whether the reusable environment matches its dependency digest."""
    try:
        state: object = json.loads(paths.sync_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict):
        return False
    return (
        bool(state.get("fingerprint") == fingerprint)
        and (paths.state_root / "venv" / "bin" / "python").is_file()
    )


def stage_cache_context(
    *,
    base: str,
    head: str,
    mode: str,
    environment: dict[str, str],
    local_digest: str,
) -> dict[str, str]:
    """Build the exact context that permits retry-stage reuse."""
    database_url = environment.get("FDAI_DATABASE_URL", "")
    return {
        "base": base,
        "head": head,
        "mode": mode,
        "integration": environment.get("FDAI_CHANGED_TEST_INTEGRATION", "0"),
        "database_digest": hashlib.sha256(database_url.encode()).hexdigest(),
        "local_input_digest": local_digest,
    }


def load_stage_cache(path: Path, context: dict[str, str]) -> set[str]:
    """Load passed stages only when their complete context still matches."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if payload.get("context") != context or not isinstance(payload.get("passed"), list):
        return set()
    return {stage for stage in payload["passed"] if isinstance(stage, str)}


def write_stage_cache(path: Path, context: dict[str, str], passed: set[str]) -> None:
    """Persist passed retry stages atomically."""
    atomic_write(
        path,
        json.dumps({"context": context, "passed": sorted(passed)}, sort_keys=True) + "\n",
    )
