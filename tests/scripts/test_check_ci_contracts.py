"""Regression coverage for repository CI workflow contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_contract_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "quality" / "ci" / "check-ci-contracts.py"
    )
    spec = importlib.util.spec_from_file_location("check_ci_contracts", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load CI contract checker: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_action_refs_reject_stale_and_unknown_remote_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "steps:\n"
        "  - uses: actions/checkout@v4\n"
        "  - uses: example/unreviewed-action@v1\n"
        "  - uses: ./.github/actions/local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_action_runtime_versions() == [
        ".github/workflows/ci.yml uses actions/checkout@v4; expected v7.0.1",
        ".github/workflows/ci.yml uses unapproved remote action example/unreviewed-action@v1",
    ]
