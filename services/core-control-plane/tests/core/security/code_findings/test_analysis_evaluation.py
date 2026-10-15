"""Tests for the owned-analysis benchmark and component inventory."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_evaluation import evaluate_python_analysis
from fdai.rule_catalog.code_security import CodeSecurityCatalogError
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_analysis_components import load_analysis_components
from fdai.rule_catalog.code_security_analysis_evaluation import (
    AnalysisEvaluationCorpus,
    load_analysis_evaluation_corpus,
)
from pydantic import ValidationError

from ._support import CATALOG_ROOT


def test_component_inventory_separates_active_planned_and_research_terms() -> None:
    inventory = load_analysis_components(CATALOG_ROOT)
    by_id = {component.id: component for component in inventory.components}

    assert by_id["tree-sitter"].status == "active"
    assert by_id["typescript"].status == "active"
    assert by_id["joern"].redistribution == "reference_only"
    assert by_id["codeql-cli"].integration == "research"


def test_component_inventory_rejects_unreviewed_active_dependency(tmp_path: Path) -> None:
    (tmp_path / "analysis-components.yaml").write_text(
        """
schema_version: 1.0.0
inventory_id: fdai.code-security.analysis-components
version: 1.0.0
components:
  - id: unsafe-component
    version: unselected
    purpose: A dependency without completed review
    status: active
    source_url: https://example.com/component
    license: LicenseRef-review-required
    redistribution: embeddable
    integration: library
""",
        encoding="utf-8",
    )

    with pytest.raises(CodeSecurityCatalogError, match="selected version"):
        load_analysis_components(tmp_path)


def test_python_evaluation_meets_split_targets_without_unsupported_cases(
    tmp_path: Path,
) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT)
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )

    receipt = evaluate_python_analysis(corpus, rule, tmp_path)

    assert receipt.dev.precision == receipt.dev.recall == receipt.dev.f1 == 1.0
    assert receipt.holdout.precision == receipt.holdout.recall == receipt.holdout.f1 == 1.0
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0
    assert receipt.duration_ms >= 0 and receipt.peak_memory_kib >= 0


def test_corpus_requires_vulnerable_and_safe_cases_in_each_split() -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT)
    dev_only = tuple(
        case.model_copy(update={"case_id": f"dev-case-{index}", "split": "dev"})
        for index, case in enumerate(corpus.cases)
    )
    with pytest.raises(ValidationError, match="each evaluation split"):
        AnalysisEvaluationCorpus.model_validate({**corpus.model_dump(), "cases": dev_only})
