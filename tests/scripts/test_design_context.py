from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_CONFIG_PATH = REPO_ROOT / ".github/hooks/design-context.json"


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/agent/design_context.py"
    spec = importlib.util.spec_from_file_location("design_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_context_composes_every_matching_route() -> None:
    module = _load_module()

    required = module.required_context(("src/fdai/delivery/read_api/dev/factory.py",))

    assert ".github/copilot-instructions.md" in required
    assert ".github/instructions/coding-conventions.instructions.md" in required
    assert ".github/instructions/app-shape.instructions.md" in required
    assert "docs/roadmap/deployment/dev-and-deploy-parity.md" in required
    assert "docs/roadmap/interfaces/operator-console.md" in required


def test_hook_avoids_post_tool_response_payloads() -> None:
    hooks = json.loads(HOOK_CONFIG_PATH.read_text(encoding="utf-8"))["hooks"]

    assert set(hooks) == {"PreToolUse"}
    assert hooks["PreToolUse"][0]["command"].endswith("design_context.py pre-tool-use")


def test_pre_tool_use_records_read_without_tool_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    state_path = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "_state_path", lambda payload: state_path)
    target = REPO_ROOT / ".github/copilot-instructions.md"
    payload = {
        "session_id": "session-read",
        "tool_name": "read_file",
        "tool_input": {"filePath": str(target), "startLine": 1, "endLine": 20},
    }

    result = module.pre_tool_use(payload)

    assert result == {"continue": True}
    recorded = json.loads(state_path.read_text(encoding="utf-8"))
    assert recorded["reads"][".github/copilot-instructions.md"] == module._sha256(target)


def test_pre_tool_use_denies_edit_without_current_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_state_path", lambda payload: tmp_path / "receipt.json")
    target = REPO_ROOT / "src/fdai/core/risk_gate/gate.py"
    payload = {
        "sessionId": "session-1",
        "toolName": "functions.apply_patch",
        "toolInput": {"input": (f"*** Begin Patch\n*** Update File: {target}\n*** End Patch")},
    }

    result = module.enforce_edit(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "architecture.instructions.md" in result["systemMessage"]


def test_recorded_current_reads_allow_edit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    state_path = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "_state_path", lambda payload: state_path)
    target = "scripts/quality/architecture/check-design-routes.py"
    payload = {
        "session_id": "session-2",
        "tool_name": "apply_patch",
        "tool_input": {
            "input": f"*** Begin Patch\n*** Update File: {REPO_ROOT / target}\n*** End Patch"
        },
    }
    reads = {
        relative: module._sha256(REPO_ROOT / relative)
        for relative in module.required_context((target,))
    }
    state_path.write_text(json.dumps({"version": 1, "reads": reads}), encoding="utf-8")

    result = module.enforce_edit(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
