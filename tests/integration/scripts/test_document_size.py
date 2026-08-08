from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-document-size.py"
    spec = importlib.util.spec_from_file_location("check_document_size", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_large_document_is_rejected() -> None:
    module = _load_module()

    errors = module.size_violations((("docs/roadmap/new.md", 401, None),))

    assert errors and "maximum is 400" in errors[0]


def test_legacy_oversized_document_must_not_grow() -> None:
    module = _load_module()

    errors = module.size_violations((("docs/roadmap/legacy.md", 701, 700),))

    assert errors and "grew 700 -> 701" in errors[0]


def test_legacy_oversized_document_may_shrink() -> None:
    module = _load_module()

    assert module.size_violations((("docs/roadmap/legacy.md", 699, 700),)) == []
