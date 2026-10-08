"""Tests for the offline evaluation harness and its synthetic corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.security.code_findings.evaluation import (
    EvaluationCorpusError,
    acceptance_failures,
    corpus_from_mapping,
    evaluate,
    kind_corpus,
    split_corpus,
    weighted_kappa,
)
from fdai.delivery.code_security_cli import main
from fdai.rule_catalog.code_security import SeverityBand

from ._support import CATALOG_ROOT, catalog

CORPUS = CATALOG_ROOT / "evaluation" / "synthetic-corpus.yaml"


def _raw() -> dict[str, Any]:
    return yaml.safe_load(CORPUS.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _case(raw: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in raw["cases"] if case["id"] == case_id)  # type: ignore[no-any-return]


def test_synthetic_corpus_meets_every_acceptance_floor() -> None:
    corpus = corpus_from_mapping(_raw())
    metrics = evaluate(corpus, catalog())
    assert corpus.provenance == "synthetic"
    assert acceptance_failures(metrics, corpus.acceptance) == []
    assert metrics.expected_issues == metrics.produced_issues == 12
    assert metrics.severity_pairs >= 9
    assert metrics.misses == ()


def test_evaluation_is_deterministic_for_the_same_corpus() -> None:
    corpus = corpus_from_mapping(_raw())
    assert evaluate(corpus, catalog()) == evaluate(corpus, catalog())
    assert corpus_from_mapping(_raw()).digest == corpus.digest


def test_mislabeled_merge_is_reported_as_false_split() -> None:
    raw = _raw()
    case = _case(raw, "distinct-classes-same-file")
    first, second = case["expected"]
    first["occurrences"] = first["occurrences"] + second["occurrences"]
    case["expected"] = [first]
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.false_split_pairs > 0
    assert metrics.dedup_recall < 1.0
    assert metrics.detection_precision < 1.0
    assert "dedup_recall" in acceptance_failures(metrics, corpus_from_mapping(raw).acceptance)


def test_wrong_fix_site_is_a_detection_miss() -> None:
    raw = _raw()
    _case(raw, "lens-only-deserialization")["expected"][0]["line"] = 24
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.detection_recall < 1.0
    assert any(miss.startswith("lens-only-deserialization:") for miss in metrics.misses)


def test_reviewer_band_disagreement_lowers_agreement_and_kappa() -> None:
    raw = _raw()
    _case(raw, "web-low-and-medium")["expected"][1]["reviewer_band"] = "critical"
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.severity_exact_agreement < 1.0
    assert metrics.severity_weighted_kappa < 1.0
    assert metrics.severity_range_containment < 1.0


def test_score_disagreement_is_one_issue_with_a_range() -> None:
    raw = _raw()
    only = copy.deepcopy(_case(raw, "dependency-aliases"))
    raw["cases"] = [only]
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.produced_issues == 2
    assert metrics.severity_range_containment == 1.0


def test_weighted_kappa_penalizes_distance() -> None:
    near = [(SeverityBand.HIGH, SeverityBand.CRITICAL), (SeverityBand.LOW, SeverityBand.LOW)]
    far = [(SeverityBand.LOW, SeverityBand.CRITICAL), (SeverityBand.LOW, SeverityBand.LOW)]
    perfect = [(SeverityBand.HIGH, SeverityBand.HIGH), (SeverityBand.LOW, SeverityBand.LOW)]
    assert weighted_kappa(perfect) == 1.0
    assert weighted_kappa(far) < weighted_kappa(near) < 1.0
    assert weighted_kappa([]) == 1.0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(schema_version=2), "schema_version"),
        (lambda raw: raw.update(provenance="customer"), "provenance"),
        (lambda raw: raw.update(acceptance={"bogus": 1.0}), "acceptance"),
        (lambda raw: raw.update(cases=[]), "cases"),
        (lambda raw: raw["cases"].append(copy.deepcopy(raw["cases"][0])), "duplicate case"),
        (
            lambda raw: raw["cases"][0]["expected"][0].update(occurrences=["missing"]),
            "known occurrence",
        ),
        (
            lambda raw: raw["cases"][0]["expected"][0].update(facts={"impact": "data_read"}),
            "invalid facts",
        ),
        (lambda raw: raw["cases"][0]["occurrences"][0].update(lane="manual"), "manual"),
        (lambda raw: raw["cases"][0]["occurrences"][0].update(line=0), "positive integer"),
    ],
)
def test_malformed_corpus_is_rejected(mutate: Any, message: str) -> None:
    raw = _raw()
    mutate(raw)
    with pytest.raises(EvaluationCorpusError, match=message):
        corpus_from_mapping(raw)


def test_occurrence_cannot_belong_to_two_expected_issues() -> None:
    raw = _raw()
    case = _case(raw, "distinct-classes-same-file")
    case["expected"][1]["occurrences"] = case["expected"][1]["occurrences"] + ["a"]
    with pytest.raises(EvaluationCorpusError, match="two expected issues"):
        corpus_from_mapping(raw)


def test_cli_evaluate_writes_a_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipt_path = tmp_path / "evaluation.json"
    assert main(["evaluate", "--output", str(receipt_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert printed == stored
    assert stored["kind"] == "fdai.code-security.evaluation-receipt"
    assert stored["corpus"]["provenance"] == "synthetic"
    assert stored["corpus"]["digest"].startswith("sha256:")
    assert set(stored["catalog_versions"]) >= {"weakness_classes", "severity_rubric"}
    assert stored["failures"] == []


def test_cli_evaluate_fails_below_acceptance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = _raw()
    _case(raw, "web-low-and-medium")["expected"][1]["reviewer_band"] = "critical"
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(["evaluate", "--corpus", str(corpus)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "severity_exact_agreement" in output["failures"]


def test_curated_advisory_corpus_meets_floors_in_both_splits() -> None:
    raw = yaml.safe_load((CATALOG_ROOT / "evaluation" / "curated-advisories.yaml").read_text())
    corpus = corpus_from_mapping(raw)
    assert corpus.provenance == "curated"
    for split in ("dev", "holdout"):
        subset = split_corpus(corpus, split)
        assert subset is not None
        assert acceptance_failures(evaluate(subset, catalog()), corpus.acceptance) == []


def test_unknown_split_is_rejected() -> None:
    raw = _raw()
    raw["cases"][0]["split"] = "test"
    with pytest.raises(EvaluationCorpusError, match="split"):
        corpus_from_mapping(raw)


def test_curated_corpus_measures_severity_agreement_for_code_and_dependencies() -> None:
    raw = yaml.safe_load((CATALOG_ROOT / "evaluation" / "curated-advisories.yaml").read_text())
    corpus = corpus_from_mapping(raw)
    for kind in ("code", "dependency"):
        subset = kind_corpus(corpus, kind)
        assert subset is not None
        for split in ("dev", "holdout"):
            part = split_corpus(subset, split)
            assert part is not None
            metrics = evaluate(part, catalog())
            assert metrics.severity_pairs == metrics.expected_issues > 0
            assert metrics.severity_range_containment == 1.0
            assert metrics.detection_recall == 1.0


def test_kind_is_derived_from_occurrences_and_validated() -> None:
    raw = _raw()
    corpus = corpus_from_mapping(raw)
    kinds = {case.case_id: case.kind for case in corpus.cases}
    assert kinds["tri-lane-sqli"] == "code"
    assert "dependency" in kinds.values()
    dependency = next(
        case
        for case in raw["cases"]
        if case.get("occurrences") and any("package" in item for item in case["occurrences"])
    )
    dependency["kind"] = "code"
    with pytest.raises(EvaluationCorpusError, match="contradicts"):
        corpus_from_mapping(raw)
    raw = _raw()
    raw["cases"][0]["kind"] = "binary"
    with pytest.raises(EvaluationCorpusError, match="kind"):
        corpus_from_mapping(raw)


def test_determined_severity_without_facts_counts_as_an_agreement_pair() -> None:
    raw = _raw()
    dependency = next(
        case
        for case in raw["cases"]
        if case.get("occurrences") and any("package" in item for item in case["occurrences"])
    )
    raw["cases"] = [dependency]
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.severity_pairs == 1
    assert metrics.severity_exact_agreement == 1.0
    dependency["expected"][1]["reviewer_band"] = "low"
    metrics = evaluate(corpus_from_mapping(raw), catalog())
    assert metrics.severity_exact_agreement == 0.0


def test_evaluation_receipt_reports_metrics_per_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt_path = tmp_path / "receipt.json"
    curated = CATALOG_ROOT / "evaluation" / "curated-advisories.yaml"
    assert main(["evaluate", "--corpus", str(curated), "--output", str(receipt_path)]) == 0
    capsys.readouterr()
    receipt = json.loads(receipt_path.read_text())
    assert set(receipt["kinds"]) == {"code", "dependency"}
    assert set(receipt["kinds"]["code"]) == {"all", "dev", "holdout"}
    assert receipt["kinds"]["code"]["all"]["severity_pairs"] == 16
