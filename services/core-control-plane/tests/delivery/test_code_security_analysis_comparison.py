"""Tests for same-condition owned-analysis comparison receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.code_security_analysis_comparison import (
    ComparisonConfig,
    compare_analysis_engines,
)
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_analysis_evaluation import (
    load_analysis_evaluation_corpus,
)

CATALOG_ROOT = Path(__file__).resolve().parents[4] / "rule-catalog" / "code-security"


def _rule():  # type: ignore[no-untyped-def]
    return next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )


def _engine(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("fake-opengrep 1.0.0")
else:
    root = Path.cwd()
    vulnerable = "vulnerable" in root.name
    source = sorted(root.glob("*.py"))[0]
    results = []
    if vulnerable:
        results.append({
            "check_id": "fdai.verify.python.sql-injection",
            "path": source.name,
            "start": {"line": 1},
        })
    print(json.dumps({"results": results, "errors": []}))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_same_materialized_cases_compare_three_engines_without_parity_claim(
    tmp_path: Path,
) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "python-sql-injection")
    receipt = compare_analysis_engines(
        corpus,
        _rule(),
        tmp_path / "work",
        ComparisonConfig(
            catalog_root=CATALOG_ROOT,
            external_engine=_engine(tmp_path / "opengrep"),
            external_rules=CATALOG_ROOT / "rules" / "verify",
        ),
    )

    engines = {item.engine: item for item in receipt.engines}
    assert receipt.parity_claimed is False
    assert receipt.corpus_digest == corpus.digest()
    assert receipt.source_files == 6 and receipt.source_bytes > 0
    assert engines["current-verifier"].dev.recall == 0.0
    assert engines["current-verifier"].holdout.recall == 1.0
    assert engines["owned-engine"].dev.recall == engines["owned-engine"].holdout.recall == 1.0
    assert engines["external-baseline"].dev.recall == 1.0
    assert engines["external-baseline"].holdout.recall == 1.0
    assert engines["external-baseline"].version == "fake-opengrep 1.0.0"
    assert b"duration_ms" not in receipt.canonical_bytes()


def test_missing_external_engine_is_explicitly_unsupported(tmp_path: Path) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "python-sql-injection")
    receipt = compare_analysis_engines(
        corpus,
        _rule(),
        tmp_path / "work",
        ComparisonConfig(catalog_root=CATALOG_ROOT),
    )

    external = next(item for item in receipt.engines if item.engine == "external-baseline")
    assert external.available is False
    assert external.dev.unsupported == external.holdout.unsupported == 2
    assert all(not item.supported for item in external.cases)


def test_recorded_semgrep_receipt_preserves_disaggregated_non_parity_evidence() -> None:
    document = json.loads(
        (CATALOG_ROOT / "evaluation" / "analysis-comparison-python-sql-1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "python-sql-injection")
    engines = {item["engine"]: item for item in document["engines"]}

    assert document["ok"] is True
    assert document["corpus_digest"] == corpus.digest()
    assert document["parity_claimed"] is False
    assert engines["current-verifier"]["dev"]["recall"] == 0.0
    assert engines["current-verifier"]["holdout"]["recall"] == 1.0
    assert engines["owned-engine"]["dev"]["recall"] == 1.0
    assert engines["owned-engine"]["holdout"]["recall"] == 1.0
    assert engines["external-baseline"]["implementation"] == "semgrep"
    assert engines["external-baseline"]["holdout"]["recall"] == 1.0


def test_recorded_typescript_receipt_marks_current_verifier_unsupported() -> None:
    document = json.loads(
        (CATALOG_ROOT / "evaluation" / "analysis-comparison-typescript-sql-1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "typescript-sql-injection")
    engines = {item["engine"]: item for item in document["engines"]}

    assert document["corpus_digest"] == corpus.digest()
    assert document["parity_claimed"] is False
    assert engines["current-verifier"]["available"] is False
    assert engines["current-verifier"]["dev"]["unsupported"] == 2
    assert engines["current-verifier"]["holdout"]["unsupported"] == 2
    assert engines["owned-engine"]["dev"]["recall"] == 1.0
    assert engines["owned-engine"]["holdout"]["recall"] == 1.0
    assert engines["external-baseline"]["implementation"] == "semgrep"


@pytest.mark.parametrize(
    ("name", "current_available", "owned_holdout", "external_holdout"),
    (
        ("analysis-comparison-python-sql-opengrep-1.0.0.json", True, 1.0, 1.0),
        ("analysis-comparison-typescript-sql-opengrep-1.0.0.json", False, 1.0, 0.0),
    ),
)
def test_recorded_opengrep_receipts_preserve_actual_engine_results(
    name: str,
    current_available: bool,
    owned_holdout: float,
    external_holdout: float,
) -> None:
    document = json.loads((CATALOG_ROOT / "evaluation" / name).read_text(encoding="utf-8"))
    engines = {item["engine"]: item for item in document["engines"]}

    assert document["parity_claimed"] is False
    assert engines["current-verifier"]["available"] is current_available
    assert engines["owned-engine"]["holdout"]["recall"] == owned_holdout
    assert engines["external-baseline"]["implementation"] == "opengrep"
    assert engines["external-baseline"]["version"] == "1.30.1"
    assert engines["external-baseline"]["holdout"]["recall"] == external_holdout
