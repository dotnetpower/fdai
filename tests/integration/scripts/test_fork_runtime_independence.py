from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-fork-runtime-independence.py"
    spec = importlib.util.spec_from_file_location("fork_runtime_independence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_tree_has_no_fork_mode_branch() -> None:
    module = _load_module()

    assert module.violations() == []
