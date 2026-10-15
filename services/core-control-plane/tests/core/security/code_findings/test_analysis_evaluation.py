"""Tests for the owned-analysis benchmark and component inventory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_evaluation import (
    evaluate_java_analysis,
    evaluate_python_analysis,
    evaluate_typescript_analysis,
)
from fdai.core.security.code_findings.java_analysis import JavaCompilerConfig
from fdai.core.security.code_findings.typescript_analysis import TypeScriptFrontendConfig
from fdai.rule_catalog.code_security import CodeSecurityCatalogError
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_analysis_components import load_analysis_components
from fdai.rule_catalog.code_security_analysis_evaluation import (
    AnalysisEvaluationCorpus,
    load_analysis_evaluation_corpus,
)
from pydantic import ValidationError

from ._support import CATALOG_ROOT, REPO_ROOT


def test_component_inventory_separates_active_planned_and_research_terms() -> None:
    inventory = load_analysis_components(CATALOG_ROOT)
    by_id = {component.id: component for component in inventory.components}

    assert by_id["tree-sitter"].status == "active"
    assert by_id["typescript"].status == "active"
    assert by_id["openjdk-javac"].license == "GPL-2.0-with-classpath-exception"
    assert by_id["roslyn"].license == "MIT"
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


@pytest.mark.parametrize(
    "name",
    (
        "python-command-injection",
        "python-path-traversal",
        "python-xss",
    ),
)
def test_python_weakness_evaluation_is_disaggregated_and_fail_closed(
    tmp_path: Path, name: str
) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, name)
    rule = next(
        item for item in load_analysis_rules(CATALOG_ROOT) if item.rule_id == corpus.rule_id
    )

    receipt = evaluate_python_analysis(corpus, rule, tmp_path)

    assert receipt.meets_initial_thresholds is True
    assert receipt.promotion_eligible is False
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0


@pytest.mark.parametrize(
    "name",
    (
        "typescript-sql-injection",
        "typescript-command-injection",
        "typescript-path-traversal",
        "typescript-xss",
    ),
)
def test_typescript_weakness_evaluation_is_disaggregated_and_fail_closed(
    tmp_path: Path, name: str
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the TypeScript evaluation frontend")
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, name)
    rule = next(
        item for item in load_analysis_rules(CATALOG_ROOT) if item.rule_id == corpus.rule_id
    )
    config = TypeScriptFrontendConfig(
        node=Path(node),
        script=REPO_ROOT / "tools" / "code-security-typescript-frontend" / "frontend.cjs",
    )

    receipt = evaluate_typescript_analysis(corpus, rule, tmp_path, config)

    assert receipt.meets_initial_thresholds is True
    assert receipt.promotion_eligible is False
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0


def test_java_evaluation_meets_split_targets_without_unsupported_cases(tmp_path: Path) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "java-sql-injection")
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.java.sql-injection"
    )

    receipt = evaluate_java_analysis(corpus, rule, tmp_path)

    assert receipt.dev.precision == receipt.dev.recall == receipt.dev.f1 == 1.0
    assert receipt.holdout.precision == receipt.holdout.recall == receipt.holdout.f1 == 1.0
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0
    assert receipt.duration_ms >= 0 and receipt.peak_memory_kib >= 0
    recorded = json.loads(
        (CATALOG_ROOT / "evaluation" / "java-analysis-1.0.0.json").read_text(encoding="utf-8")
    )
    recorded.pop("resources")
    assert recorded == receipt.stable_dict()


def test_compiler_backed_java_evaluation_is_disaggregated_and_shadow_only(tmp_path: Path) -> None:
    java = shutil.which("java")
    if java is None:
        pytest.skip("a JDK is required for compiler-backed Java evaluation")
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "java-compiler-sql-injection")
    rule = next(
        item for item in load_analysis_rules(CATALOG_ROOT) if item.rule_id == corpus.rule_id
    )

    receipt = evaluate_java_analysis(
        corpus,
        rule,
        tmp_path,
        JavaCompilerConfig(
            java=Path(java),
            helper=REPO_ROOT / "tools" / "code-security-java-frontend" / "FdaiJavaSymbols.java",
        ),
    )

    assert receipt.meets_initial_thresholds is True
    assert receipt.promotion_eligible is False
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0
    assert receipt.dev.precision == receipt.dev.recall == 1.0
    assert receipt.holdout.precision == receipt.holdout.recall == 1.0
    recorded = json.loads(
        (CATALOG_ROOT / "evaluation" / "java-compiler-analysis-1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    recorded.pop("resources")
    assert recorded == receipt.stable_dict()


def test_corpus_requires_vulnerable_and_safe_cases_in_each_split() -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT)
    dev_only = tuple(
        case.model_copy(update={"case_id": f"dev-case-{index}", "split": "dev"})
        for index, case in enumerate(corpus.cases)
    )
    with pytest.raises(ValidationError, match="each evaluation split"):
        AnalysisEvaluationCorpus.model_validate({**corpus.model_dump(), "cases": dev_only})


def test_recorded_weakness_receipts_remain_disaggregated_and_shadow_only() -> None:
    document = json.loads(
        (CATALOG_ROOT / "evaluation" / "analysis-weakness-shadow-1.0.0.json").read_text(
            encoding="utf-8"
        )
    )

    assert document["promotion_eligible"] is False
    assert len(document["receipts"]) == 6
    assert all(item["dev"]["f1"] == item["holdout"]["f1"] == 1.0 for item in document["receipts"])
    assert all(item["promotion_eligible"] is False for item in document["receipts"])


def test_package_hardening_receipt_closes_medium_or_higher_findings() -> None:
    document = json.loads(
        (CATALOG_ROOT / "evaluation" / "analysis-hardening-packages-0-5-20261015.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(document["rounds"]) >= 10
    assert len({item["lens"] for item in document["rounds"]}) >= 10
    assert document["final_findings"] == {"critical": 0, "high": 0, "medium": 0, "low": 2}
    assert document["claims"]["production_promotion"] is False
