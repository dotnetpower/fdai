from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "automation" / "next-version.py"
    spec = importlib.util.spec_from_file_location("next_version", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_starts_at_0_1_1_without_version_tags() -> None:
    module = _load_module()

    assert module.next_version([]) == "0.1.1"


def test_increments_the_highest_semantic_version_patch() -> None:
    module = _load_module()

    assert module.next_version(["v0.1.9", "v0.1.10", "v0.2.0"]) == "0.2.1"


def test_ignores_non_release_tags() -> None:
    module = _load_module()

    assert module.next_version(["release", "v0.1.2-rc1"]) == "0.1.1"


def test_release_version_is_prepared_only_by_manual_dispatch() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "automatic-version.yml").read_text(
        encoding="utf-8"
    )

    trigger = workflow.split("permissions:", 1)[0]
    assert "  workflow_dispatch:" in trigger
    assert "  push:" not in trigger
    assert "if: github.ref == 'refs/heads/main'" in workflow
