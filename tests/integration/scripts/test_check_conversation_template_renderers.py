"""Focused tests for check-conversation-template-renderers.py (L5 ratchet gate)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "quality" / "architecture" / "check-conversation-template-renderers.py"
)


def _load_gate():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("check_conv_templates", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_repository_passes_conversation_template_renderer_gate() -> None:
    gate = _load_gate()
    assert gate.violations(REPO_ROOT) == []


def test_gate_rejects_new_template_answer_or_regex_or_keyword_table_in_conversation_path(
    tmp_path: Path,
) -> None:
    gate = _load_gate()
    conv_dir = (
        tmp_path / "services" / "core-control-plane" / "src" / "fdai" / "core" / "conversation"
    )
    conv_dir.mkdir(parents=True)
    allow_dir = tmp_path / "scripts" / "quality" / "architecture"
    allow_dir.mkdir(parents=True)

    existing = conv_dir / "legacy_allowed.py"
    existing.write_text("import re\n_PAT = re.compile(r'foo')\n", encoding="utf-8")
    new_template = conv_dir / "new_template_renderer.py"
    new_template.write_text(
        "def render_custom_answer(rows: list[str]) -> str:\n    return ','.join(rows)\n",
        encoding="utf-8",
    )

    allowlist = {
        "version": 1,
        "lane": "L5-legacy-removal",
        "owner": "docs/roadmap/interfaces/ontology-reasoning-coverage.md",
        "allowlisted_paths": [
            "services/core-control-plane/src/fdai/core/conversation/legacy_allowed.py"
        ],
    }
    (allow_dir / "conversation-template-renderers-allowlist.json").write_text(
        json.dumps(allowlist), encoding="utf-8"
    )

    errs = gate.violations(tmp_path)
    assert any("new_template_renderer.py" in e for e in errs)


def test_gate_flags_stale_allowlist_entry_to_enforce_monotonic_l5_ratchet(
    tmp_path: Path,
) -> None:
    gate = _load_gate()
    conv_dir = (
        tmp_path / "services" / "core-control-plane" / "src" / "fdai" / "core" / "conversation"
    )
    conv_dir.mkdir(parents=True)
    allow_dir = tmp_path / "scripts" / "quality" / "architecture"
    allow_dir.mkdir(parents=True)

    clean = conv_dir / "cleaned_module.py"
    clean.write_text("def pure_helper(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    allowlist = {
        "version": 1,
        "lane": "L5-legacy-removal",
        "owner": "docs/roadmap/interfaces/ontology-reasoning-coverage.md",
        "allowlisted_paths": [
            "services/core-control-plane/src/fdai/core/conversation/cleaned_module.py"
        ],
    }
    (allow_dir / "conversation-template-renderers-allowlist.json").write_text(
        json.dumps(allowlist), encoding="utf-8"
    )

    errs = gate.violations(tmp_path)
    assert any("stale conversation template/regex allowlist entry" in e for e in errs)
