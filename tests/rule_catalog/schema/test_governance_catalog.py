"""Directory loader for the governance catalog-as-code."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
from fdai.rule_catalog.schema.governance_loader import GovernanceLoadError

_VALID_ASSIGNMENT = """
schema_version: "1.0.0"
id: "assign-baseline-rg-a"
target_rule_ids: ["r.encryption"]
scope:
  level: "resource-group"
  id: "rg-a"
effect: "audit"
"""

_VALID_RULE_SET = """
schema_version: "1.0.0"
id: "security-baseline"
version: "1.0.0"
members:
  - rule_id: "r.encryption"
    version: "1.0.0"
    default_effect: "deny"
"""


def _write(root: Path, kind: str, name: str, body: str) -> None:
    d = root / kind
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def test_empty_root_is_empty_catalog(tmp_path: Path) -> None:
    cat = load_governance_catalog(tmp_path)
    assert cat.assignments == ()
    assert cat.rule_sets == ()


def test_loads_assignments_and_rule_sets(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "a.yaml", _VALID_ASSIGNMENT)
    _write(tmp_path, "rule-sets", "s.yaml", _VALID_RULE_SET)
    cat = load_governance_catalog(tmp_path)
    assert [a.id for a in cat.assignments] == ["assign-baseline-rg-a"]
    assert [r.id for r in cat.rule_sets] == ["security-baseline"]


def test_invalid_document_is_reported_with_file_key(tmp_path: Path) -> None:
    # missing required fields (target_rule_ids, scope)
    _write(tmp_path, "assignments", "bad.yaml", 'schema_version: "1.0.0"\nid: "x"\n')
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any(i.key.startswith("bad.yaml") for i in ei.value.issues)


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "assignments", "a1.yaml", _VALID_ASSIGNMENT)
    _write(tmp_path, "assignments", "a2.yaml", _VALID_ASSIGNMENT)  # same id
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("duplicate id" in i.message for i in ei.value.issues)


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "rule-sets", "list.yaml", "- just\n- a\n- list\n")
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("not a YAML mapping" in i.message for i in ei.value.issues)


def test_domain_invariant_duplicate_member_caught(tmp_path: Path) -> None:
    dup_member = """
schema_version: "1.0.0"
id: "dup-set"
version: "1.0.0"
members:
  - rule_id: "r.x"
    version: "1.0.0"
  - rule_id: "r.x"
    version: "2.0.0"
"""
    _write(tmp_path, "rule-sets", "dup.yaml", dup_member)
    with pytest.raises(GovernanceLoadError) as ei:
        load_governance_catalog(tmp_path)
    assert any("duplicate member" in i.message for i in ei.value.issues)
