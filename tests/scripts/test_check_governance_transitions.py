"""Governance transition CI-gate script - ref validation and helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "governance" / "check-governance-transitions.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_governance_transitions", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MOD = _load_script()


def test_ref_exists_true_for_head() -> None:
    assert _MOD._ref_exists("HEAD") is True


def test_ref_exists_false_for_bogus_ref() -> None:
    assert _MOD._ref_exists("definitely-not-a-real-ref-zzz-000") is False


def test_load_from_ref_fails_loud_on_bad_ref() -> None:
    # a misconfigured base ref must fail loudly, not silently compare to empty
    with pytest.raises(SystemExit, match="does not resolve"):
        _MOD._load_from_ref("definitely-not-a-real-ref-zzz-000", "rule-catalog/governance")


def test_load_from_tree_missing_root_is_empty(tmp_path: Path) -> None:
    cat = _MOD._load_from_tree(tmp_path / "no-such-dir")
    assert cat.assignments == ()
    assert cat.rule_sets == ()


def test_read_approved_parses_ids_comments_blanks(tmp_path: Path) -> None:
    f = tmp_path / "approved.txt"
    f.write_text(
        "# promotions\nassign-a\n\nassign-b   # inline comment\n   \n",
        encoding="utf-8",
    )
    assert _MOD._read_approved(f) == frozenset({"assign-a", "assign-b"})


def test_read_approved_none_is_empty() -> None:
    assert _MOD._read_approved(None) == frozenset()
