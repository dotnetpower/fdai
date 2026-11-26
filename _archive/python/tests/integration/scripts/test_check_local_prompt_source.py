from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/check-local-prompt-source.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_local_prompt_source", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dirty_prompt_paths_joins_modified_and_untracked(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    calls: list[tuple[str, ...]] = []

    def fake_git_paths(_root: Path, *args: str) -> tuple[str, ...]:
        calls.append(args)
        return (
            ("rule-catalog/prompts/base/conversation-preflight.v3.yaml",)
            if args[0] == "diff"
            else ("rule-catalog/prompts/base/conversation-preflight.v4.yaml",)
        )

    monkeypatch.setattr(module, "_git_paths", fake_git_paths)

    assert module.dirty_prompt_paths(tmp_path) == (
        "rule-catalog/prompts/base/conversation-preflight.v3.yaml",
        "rule-catalog/prompts/base/conversation-preflight.v4.yaml",
    )
    assert len(calls) == 2


def test_clean_prompt_source_has_no_paths(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_git_paths", lambda _root, *_args: ())

    assert module.dirty_prompt_paths(tmp_path) == ()


def test_diagnostics_never_reach_stdout(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(
        module, "dirty_prompt_paths", lambda _root: ("rule-catalog/prompts/a.yaml",)
    )

    monkeypatch.setenv("FDAI_LOCAL_ALLOW_DIRTY_PROMPTS", "1")
    assert module.main() == 0
    allowed = capsys.readouterr()
    monkeypatch.delenv("FDAI_LOCAL_ALLOW_DIRTY_PROMPTS")
    assert module.main() == 1
    blocked = capsys.readouterr()

    # A caller reading an input digest from stdout sees only the digest.
    assert allowed.out == "" and blocked.out == ""
    assert "opt-in is active" in allowed.err and "start blocked" in blocked.err
