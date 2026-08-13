from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/quality/documentation/check-action-runbooks.py"


def _write_action_type(root: Path, name: str) -> None:
    action_types = root / "rule-catalog/action-types"
    action_types.mkdir(parents=True, exist_ok=True)
    (action_types / f"{name}.yaml").write_text(f"name: {name}\n", encoding="utf-8")


def _write_runbook(
    root: Path,
    name: str,
    *,
    patterns: tuple[str, ...],
    include_verification: bool = True,
) -> None:
    runbooks = root / "docs/runbooks"
    runbooks.mkdir(parents=True, exist_ok=True)
    pattern_lines = "".join(f"    - {pattern}\n" for pattern in patterns)
    verification = (
        "## Verification\nConfirm the intended effect.\n\n" if include_verification else ""
    )
    (runbooks / f"{name}.md").write_text(
        "---\n"
        "title: Test runbook\n"
        "fdai_runbook:\n"
        "  schema_version: 1.0.0\n"
        "  action_type_patterns:\n"
        f"{pattern_lines}"
        "  sections:\n"
        "    preconditions: Preconditions\n"
        "    procedure: Procedure\n"
        "    verification: Verification\n"
        "    rollback: Rollback\n"
        "    audit_trail: Audit trail\n"
        "---\n"
        "# Test runbook\n\n"
        "## Preconditions\nCheck prerequisites.\n\n"
        "## Procedure\nPerform the governed action.\n\n"
        f"{verification}"
        "## Rollback\nUndo the operator step.\n\n"
        "## Audit trail\nRecord the outcome.\n",
        encoding="utf-8",
    )


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed checker with a test-owned root.
        [sys.executable, str(SCRIPT), "--root", str(root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    _write_action_type(tmp_path, "ops.restart-service")
    _write_runbook(tmp_path, "operations", patterns=("ops.*",))
    return tmp_path


def test_complete_action_type_coverage_passes(catalog_root: Path) -> None:
    result = _run(catalog_root)

    assert result.returncode == 0, result.stderr
    assert "OK (1 ActionType(s), 1 runbook(s))" in result.stdout


def test_uncovered_action_type_fails(catalog_root: Path) -> None:
    _write_action_type(catalog_root, "governance.grant-exemption")

    result = _run(catalog_root)

    assert result.returncode == 1
    assert "governance.grant-exemption: no operator runbook matches" in result.stderr


def test_duplicate_action_type_coverage_fails(catalog_root: Path) -> None:
    _write_runbook(catalog_root, "duplicate", patterns=("ops.restart-*",))

    result = _run(catalog_root)

    assert result.returncode == 1
    assert "ops.restart-service: multiple operator runbooks match" in result.stderr
    assert "duplicate.md" in result.stderr
    assert "operations.md" in result.stderr


def test_missing_required_section_fails(catalog_root: Path) -> None:
    _write_runbook(
        catalog_root,
        "operations",
        patterns=("ops.*",),
        include_verification=False,
    )

    result = _run(catalog_root)

    assert result.returncode == 1
    assert "operations.md: required heading '## Verification' is missing" in result.stderr


def test_shipped_action_types_have_valid_runbook_coverage() -> None:
    result = _run(REPO_ROOT)

    assert result.returncode == 0, result.stderr
    assert "OK (48 ActionType(s)" in result.stdout


def test_checker_is_wired_into_ci_and_local_gates() -> None:
    command = "scripts/quality/documentation/check-action-runbooks.py"
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    verify = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    pre_commit = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert f"uv run python {command}" in workflow
    assert f"uv run python {command}" in verify
    assert f"python3 {command}" in pre_commit
