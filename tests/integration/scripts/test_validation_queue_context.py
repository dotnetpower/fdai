from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "automation" / "validation_queue_context.py"
    spec = importlib.util.spec_from_file_location("validation_queue_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_background_worker_recommendation_is_capped_at_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("FDAI_VALIDATION_BACKGROUND", "1")
    monkeypatch.setattr(module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(module.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(module, "_available_memory_bytes", lambda: 16 * 1024**3)

    assert module._recommended_workers() == "2"


def test_foreground_worker_recommendation_keeps_adaptive_parallelism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.delenv("FDAI_VALIDATION_BACKGROUND", raising=False)
    monkeypatch.setattr(module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(module.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(module, "_available_memory_bytes", lambda: 16 * 1024**3)

    assert module._recommended_workers() == "4"


def test_validation_environment_drops_hook_local_git_pointers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    for variable in module._REPOSITORY_LOCAL_GIT_ENV:
        monkeypatch.setenv(variable, f"hook-{variable.lower()}")
    global_config = str(tmp_path / "global-git-config")
    system_config = str(tmp_path / "system-git-config")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", global_config)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", system_config)
    paths = SimpleNamespace(
        repo_root=tmp_path / "repo",
        state_root=tmp_path / "state",
    )

    environment = module.validation_environment(paths)

    assert module._REPOSITORY_LOCAL_GIT_ENV.isdisjoint(environment)
    assert environment["GIT_CONFIG_GLOBAL"] == global_config
    assert environment["GIT_CONFIG_SYSTEM"] == system_config


def test_validation_environment_pins_python_313_despite_primary_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    primary_python = tmp_path / "repo" / ".venv" / "bin" / "python"
    primary_python.parent.mkdir(parents=True)
    primary_python.touch()
    monkeypatch.setenv("UV_PYTHON", str(primary_python))
    monkeypatch.setenv("FDAI_VALIDATION_DATABASE_URL", "postgresql://validation")
    paths = SimpleNamespace(
        repo_root=tmp_path / "repo",
        state_root=tmp_path / "state",
    )

    environment = module.validation_environment(paths)

    assert environment["UV_PYTHON"] == "3.13"
