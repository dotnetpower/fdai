"""_load_parameter_relaxation_policies - missing file is empty, present file loads."""

from __future__ import annotations

from pathlib import Path

from fdai.runtime.control_loop import _load_parameter_relaxation_policies


def test_missing_policy_file_is_empty(tmp_path: Path) -> None:
    assert _load_parameter_relaxation_policies(tmp_path) == {}


def test_present_policy_file_loads(tmp_path: Path) -> None:
    (tmp_path / "override-parameter-bounds.yaml").write_text(
        "rules:\n  example.rule.x:\n    min_retention_days: {minimum: 1, maximum: 30}\n",
        encoding="utf-8",
    )

    policies = _load_parameter_relaxation_policies(tmp_path)

    assert "example.rule.x" in policies
    assert policies["example.rule.x"].allows("min_retention_days", "3")
    assert not policies["example.rule.x"].allows("min_retention_days", "999")


def test_empty_policy_file_is_empty(tmp_path: Path) -> None:
    (tmp_path / "override-parameter-bounds.yaml").write_text("rules: {}\n", encoding="utf-8")

    assert _load_parameter_relaxation_policies(tmp_path) == {}
