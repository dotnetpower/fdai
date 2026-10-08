"""Tests for the strict code-security catalog loader."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.code_security import (
    CodeSecurityCatalogError,
    load_code_security_catalog,
)

from ._support import CATALOG_ROOT, catalog


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "code-security"
    shutil.copytree(CATALOG_ROOT, target)
    return target


def _edit(path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    document = yaml.safe_load(path.read_text())
    mutate(document)
    path.write_text(yaml.safe_dump(document))


def test_shipped_catalog_loads_with_versions() -> None:
    loaded = catalog()
    assert loaded.version_stamp()["severity_rubric"] == "1.1.0"
    assert loaded.weakness_classes.class_for_cwe(89) == "sql_injection"
    assert loaded.weakness_classes.class_for_cwe(20) is None


def test_cwe_owned_by_two_classes_is_rejected(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(
        root / "weakness-classes.yaml",
        lambda d: d["classes"]["xml_external_entity"]["cwe"].append(89),
    )
    with pytest.raises(CodeSecurityCatalogError, match="CWE-89"):
        load_code_security_catalog(root)


def test_manual_eligibility_requires_plan_only(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(
        root / "weakness-classes.yaml",
        lambda d: d["classes"]["authentication_bypass"].update(max_depth="D2"),
    )
    with pytest.raises(CodeSecurityCatalogError, match="plan_only"):
        load_code_security_catalog(root)


def test_invalid_guard_pattern_is_rejected(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(
        root / "remediation-policy.yaml",
        lambda d: d["forbidden_added_patterns"].append(
            {"id": "broken", "pattern": "([", "description": "bad"}
        ),
    )
    with pytest.raises(CodeSecurityCatalogError, match="does not compile"):
        load_code_security_catalog(root)


def test_incomplete_rubric_table_is_rejected(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root / "severity-rubric.yaml", lambda d: d["attack_vector_penalty"].pop("physical"))
    with pytest.raises(CodeSecurityCatalogError, match="attack_vector_penalty"):
        load_code_security_catalog(root)


def test_missing_template_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / "remediation-pack" / "REMEDIATE.prompt.md").unlink()
    with pytest.raises(CodeSecurityCatalogError, match="missing pack template"):
        load_code_security_catalog(root)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _edit(root / "priority-policy.yaml", lambda d: d["rules"][0]["when"].update(surprise=True))
    with pytest.raises(CodeSecurityCatalogError):
        load_code_security_catalog(root)
