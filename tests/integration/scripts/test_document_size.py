from __future__ import annotations

import importlib.util
import subprocess
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


def test_cached_mode_compares_index_snapshot_to_head(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _load_module()
    calls: list[tuple[str, ...]] = []

    def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="one\ntwo\n", stderr="")

    monkeypatch.setattr(module, "_run_git", run_git)

    assert module._base_ref("--cached") == "HEAD"
    assert module._diff_arguments("--cached") == (
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMRT",
    )
    assert module._current_line_count("docs/roadmap/example.md", "--cached") == 2
    assert calls == [("show", ":docs/roadmap/example.md")]


def test_unknown_option_is_rejected() -> None:
    module = _load_module()

    assert module.main(["check-document-size.py", "--all"]) == 2
