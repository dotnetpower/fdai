from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-chat-semantic-routing.py"
    spec = importlib.util.spec_from_file_location("check_chat_semantic_routing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(path: str, *, disposition: str = "migrate", issue: int = 252) -> dict[str, object]:
    return {
        "path": path,
        "disposition": disposition,
        "owner": "semantic-conversation",
        "reason": "Reviewed natural-language semantic judgment baseline entry.",
        "issue": issue,
    }


def _write_baseline(root: Path, candidates: list[dict[str, object]]) -> None:
    path = root / "scripts/quality/architecture/chat-semantic-routing-baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "candidates": candidates}, indent=2) + "\n",
        encoding="utf-8",
    )


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_current_repository_semantic_baseline_is_complete() -> None:
    assert _load_module().violations() == []


def test_detector_scans_every_production_source_tree() -> None:
    module = _load_module()
    actual = {path.resolve() for path in module._production_roots(REPO_ROOT)}
    expected = {
        (REPO_ROOT / "console/src").resolve(),
        (REPO_ROOT / "cli/src").resolve(),
    }
    expected.update(
        source_root.resolve()
        for parent in (REPO_ROOT / "services", REPO_ROOT / "packages")
        for package in parent.iterdir()
        if (source_root := package / "src").is_dir()
    )

    assert len(expected) >= 8
    assert actual == expected


def test_diff_scoped_verify_triggers_for_every_production_root() -> None:
    verify = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    gate_line = next(
        line for line in verify.splitlines() if 'run_gate_scoped "chat-semantic-routing"' in line
    )

    for root in ("services/", "packages/", "console/", "cli/"):
        assert root in gate_line
    assert "services/operator-service/" not in gate_line


def test_new_python_lexical_semantic_classifier_fails(tmp_path: Path) -> None:
    relative = "services/core-control-plane/src/fdai/core/conversation/new_intent_router.py"
    _write(
        tmp_path,
        relative,
        "import re\n_INTENT_CUE = re.compile(r'why')\n"
        "def route(utterance: str) -> bool:\n"
        "    return _INTENT_CUE.search(utterance.casefold()) is not None\n",
    )
    _write_baseline(tmp_path, [])

    findings = _load_module().violations(tmp_path)

    assert findings == [f"unreviewed lexical semantic judgment path: {relative}"]


def test_python_alias_and_direct_membership_cannot_bypass_the_gate(tmp_path: Path) -> None:
    relative = "services/core-control-plane/src/fdai/core/conversation/alias_router.py"
    _write(
        tmp_path,
        relative,
        "def decide(msg: str) -> str:\n"
        "    text = msg.casefold()\n"
        "    return 'budget' if 'spend' in text else 'other'\n",
    )
    _write_baseline(tmp_path, [])

    findings = _load_module().violations(tmp_path)

    assert findings == [f"unreviewed lexical semantic judgment path: {relative}"]


def test_new_typescript_lexical_semantic_classifier_fails(tmp_path: Path) -> None:
    relative = "console/src/deck/new-answerer.ts"
    _write(
        tmp_path,
        relative,
        "export function answer(q: string): boolean {\n  return /why|status/.test(q);\n}\n",
    )
    _write_baseline(tmp_path, [])

    findings = _load_module().violations(tmp_path)

    assert findings == [f"unreviewed lexical semantic judgment path: {relative}"]


def test_typescript_arrow_and_normalized_includes_cannot_bypass_the_gate(
    tmp_path: Path,
) -> None:
    relative = "console/src/routes/alias-router.ts"
    _write(
        tmp_path,
        relative,
        "export const decide = (message: string): string => {\n"
        "  const normalized = message.toLowerCase();\n"
        "  return normalized.includes('budget') ? 'budget' : 'other';\n"
        "};\n",
    )
    _write_baseline(tmp_path, [])

    findings = _load_module().violations(tmp_path)

    assert findings == [f"unreviewed lexical semantic judgment path: {relative}"]


def test_reviewed_retain_exception_is_explicit_and_allowed(tmp_path: Path) -> None:
    relative = "services/core-control-plane/src/fdai/core/conversation/output_guard.py"
    _write(
        tmp_path,
        relative,
        "def validate(question: str) -> bool:\n    return question.casefold() == 'safe'\n",
    )
    _write_baseline(tmp_path, [_candidate(relative, disposition="retain")])

    assert _load_module().violations(tmp_path) == []


def test_stale_baseline_entry_fails_after_lexical_logic_is_removed(tmp_path: Path) -> None:
    relative = "services/core-control-plane/src/fdai/core/conversation/retired_router.py"
    _write(tmp_path, relative, "def route(value: str) -> bool:\n    return bool(value)\n")
    _write_baseline(tmp_path, [_candidate(relative)])

    assert _load_module().violations(tmp_path) == [
        f"stale lexical semantic baseline path: {relative}"
    ]


def test_baseline_requires_issue_252_and_unique_paths(tmp_path: Path) -> None:
    relative = "services/core-control-plane/src/fdai/core/conversation/router.py"
    _write(
        tmp_path,
        relative,
        "def route(question: str) -> bool:\n    return bool(question.casefold())\n",
    )
    entry = _candidate(relative, issue=999)
    _write_baseline(tmp_path, [entry, entry])

    findings = _load_module().violations(tmp_path)

    assert f"semantic baseline issue must be 252: {relative}" in findings
    assert f"semantic baseline path is duplicated: {relative}" in findings
