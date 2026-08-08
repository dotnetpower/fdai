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

    required = module.required_context(("src/fdai/delivery/operator_api/dev/factory.py",))

    assert ".github/copilot-instructions.md" in required
    assert "docs/roadmap/architecture/fdai-constitution.md" in required
    assert ".github/instructions/coding-conventions.instructions.md" in required
    assert ".github/instructions/app-shape.instructions.md" in required
    assert "docs/roadmap/deployment/dev-and-deploy-parity.md" in required
    assert "docs/roadmap/interfaces/operator-console.md" in required


def test_constitutional_surface_requires_canonical_context() -> None:
    module = _load_module()

    required = module.required_context((".github/instructions/architecture.instructions.md",))

    assert "docs/roadmap/architecture/fdai-constitution.md" in required
    assert "docs/roadmap/decisioning/risk-classification.md" in required
    assert "docs/roadmap/decisioning/escalation-and-standing-authority.md" in required


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

    result = module.pre_tool_use(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "architecture.instructions.md" in result["systemMessage"]


def test_pre_tool_use_allows_normal_edit_without_design_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_state_path", lambda payload: tmp_path / "receipt.json")
    target = REPO_ROOT / "src/fdai/delivery/operator_api/dev/factory.py"
    payload = {
        "sessionId": "session-normal-edit",
        "toolName": "functions.apply_patch",
        "toolInput": {"input": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"},
    }

    assert module.pre_tool_use(payload) == {"continue": True}


def test_pre_tool_use_does_not_record_ordinary_source_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    state_path = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "_state_path", lambda payload: state_path)
    payload = {
        "session_id": "session-source-read",
        "tool_name": "read_file",
        "tool_input": {"filePath": str(REPO_ROOT / "scripts/agent/design_context.py")},
    }

    assert module.pre_tool_use(payload) == {"continue": True}
    assert not state_path.exists()


def test_recorded_current_reads_allow_edit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    state_path = tmp_path / "receipt.json"
    monkeypatch.setattr(module, "_state_path", lambda payload: state_path)
    target = "scripts/agent/design_context.py"
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


@pytest.mark.parametrize(
    "command",
    [
        "bash scripts/verify.sh --fast",
        "scripts/verify.sh --all",
        "make check",
        "make test",
        "make operator",
        "make lint",
        "make gates",
        "make test-changed",
        "uv run pytest -q --no-cov",
        "uv run mypy",
        "bash scripts/quality/ci/run-python-tests.sh",
        "bash scripts/quality/ci/run-operator-surfaces.sh",
    ],
)
def test_pre_tool_use_routes_heavy_terminal_validation_to_queue(command: str) -> None:
    module = _load_module()
    payload = {
        "session_id": "worker-session",
        "tool_name": "run_in_terminal",
        "tool_input": {"command": command},
    }

    result = module.pre_tool_use(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "make validation-run" in result["systemMessage"]


def test_pre_tool_use_allows_central_validation_runner() -> None:
    module = _load_module()
    payload = {
        "session_id": "integration-session",
        "tool_name": "run_in_terminal",
        "tool_input": {"command": "make validation-run"},
    }

    assert module.pre_tool_use(payload) == {"continue": True}


def test_pre_tool_use_allows_focused_verify_path() -> None:
    module = _load_module()
    payload = {
        "tool_name": "run_in_terminal",
        "tool_input": {
            "command": "bash scripts/verify.sh --full tests/scripts/test_design_context.py"
        },
    }

    assert module.pre_tool_use(payload) == {"continue": True}


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest -q --no-cov tests/scripts/test_design_context.py",
        "uv run mypy scripts/agent/design_context.py",
        "make test-changed DIFF=HEAD^..HEAD",
    ],
)
def test_pre_tool_use_allows_focused_cli_checks(command: str) -> None:
    module = _load_module()
    payload = {
        "tool_name": "run_in_terminal",
        "tool_input": {"command": command},
    }

    assert module.pre_tool_use(payload) == {"continue": True}


def test_pre_tool_use_denies_only_unscoped_test_tool() -> None:
    module = _load_module()
    broad = {
        "tool_name": "runTests",
        "tool_input": {},
    }
    focused = {
        "tool_name": "runTests",
        "tool_input": {"files": ["tests/scripts/test_design_context.py"]},
    }

    assert module.pre_tool_use(broad)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert module.pre_tool_use(focused) == {"continue": True}


@pytest.mark.parametrize(
    "command",
    [
        "gh run watch 123",
        "gh workflow run deploy-dev.yml",
        "terraform plan",
        "azd provision --preview",
        "docker build -t example/fdai .",
        "docker compose up --build",
        "az acr build -r example -t fdai:dev .",
        "az group create -n example -l koreacentral",
        "bash scripts/deployment/azure/azd-up.sh",
    ],
)
def test_pre_tool_use_defers_slow_external_work_until_head_is_validated(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.external_operation_guard,
        "_head_has_validation_receipt",
        lambda repo_root: False,
    )
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": command}}

    result = module.pre_tool_use(payload)

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "check-commit HEAD" in result["systemMessage"]


def test_pre_tool_use_allows_slow_external_work_for_validated_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.external_operation_guard,
        "_head_has_validation_receipt",
        lambda repo_root: True,
    )
    payload = {
        "tool_name": "run_in_terminal",
        "tool_input": {"command": "gh run view 123 --log"},
    }

    assert module.pre_tool_use(payload) == {"continue": True}


@pytest.mark.parametrize(
    "command",
    [
        "az account show",
        "docker version",
        "gh issue view 123",
        "git fetch origin main",
    ],
)
def test_pre_tool_use_allows_lightweight_external_preflight(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.external_operation_guard,
        "_head_has_validation_receipt",
        lambda repo_root: False,
    )
    payload = {"tool_name": "run_in_terminal", "tool_input": {"command": command}}

    assert module.pre_tool_use(payload) == {"continue": True}
