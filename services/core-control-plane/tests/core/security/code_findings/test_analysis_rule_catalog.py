"""Tests for the owned code-security analysis rule catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.code_security import CodeSecurityCatalogError
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

from ._support import CATALOG_ROOT


def test_shipped_analysis_rule_catalog_is_strict_and_versioned() -> None:
    (rule,) = load_analysis_rules(CATALOG_ROOT)

    assert rule.rule_id == "fdai.python.sql-injection"
    assert rule.version == "1.0.0"
    assert rule.cwe_ids == (89,)
    assert {selector.role for selector in rule.selectors} >= {"source", "sink", "sanitizer"}


def test_analysis_rule_loader_rejects_unknown_fields_and_duplicate_identity(
    tmp_path: Path,
) -> None:
    source = yaml.safe_load(
        (CATALOG_ROOT / "analysis-rules" / "python-sql-injection.yaml").read_text()
    )
    root = tmp_path / "catalog"
    directory = root / "analysis-rules"
    directory.mkdir(parents=True)
    (directory / "a.yaml").write_text(yaml.safe_dump(source))
    duplicate = dict(source)
    duplicate["unexpected"] = True
    (directory / "b.yaml").write_text(yaml.safe_dump(duplicate))

    with pytest.raises(CodeSecurityCatalogError, match="unexpected"):
        load_analysis_rules(root)

    (directory / "b.yaml").write_text(yaml.safe_dump(source))
    with pytest.raises(CodeSecurityCatalogError, match="duplicate"):
        load_analysis_rules(root)
