from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
