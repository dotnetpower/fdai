from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ACTION = (_ROOT / ".github/actions/verify-protected-workflow-source/action.yml").read_text(
    encoding="utf-8"
)


def test_protected_workflow_action_fails_closed() -> None:
    assert "using: composite" in _ACTION
    assert '[[ "$TARGET_COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]' in _ACTION
    assert "[.]github/workflows/[A-Za-z0-9._-]+[.]ya?ml" in _ACTION
    assert "+refs/heads/main:refs/remotes/origin/main" in _ACTION
    assert "merge-base --is-ancestor" in _ACTION
    assert '"$TARGET_COMMIT_SHA:$PROTECTED_WORKFLOW_PATH"' in _ACTION
    assert '"refs/remotes/origin/main:$PROTECTED_WORKFLOW_PATH"' in _ACTION
    assert "::add-mask::$auth_header" in _ACTION


def test_protected_workflow_action_uses_only_declared_inputs() -> None:
    for name in (
        "target-commit-sha",
        "workflow-path",
        "origin-url",
        "github-token",
    ):
        assert f"  {name}:" in _ACTION
        assert f"inputs.{name}" in _ACTION
