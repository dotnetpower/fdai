"""Tests for verifier precision metrics and the real-code verifier corpus format."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from fdai.core.security.code_findings.verifier_evaluation import (
    ExpectedResults,
    LabeledLocation,
    LocationOutcome,
    VerifierCorpusError,
    load_verifier_corpus,
    promoted_keys,
    verifier_metrics,
)

from ._support import CATALOG_ROOT


def _raw() -> dict[str, Any]:
    return yaml.safe_load(  # type: ignore[no-any-return]
        (CATALOG_ROOT / "evaluation" / "verifier-corpus.yaml").read_text(encoding="utf-8")
    )


def _location(
    path: str,
    line: int | None,
    cls: str,
    *,
    vulnerable: bool,
    verifier: str = "taint",
    split: str = "dev",
) -> LabeledLocation:
    return LabeledLocation("s", path, line, cls, verifier, vulnerable, split)


def test_metrics_count_outcomes_per_split_and_gate_promotion_on_both() -> None:
    tp = _location("a.ts", 1, "sql_injection", vulnerable=True)
    held_tp = _location("h.ts", 1, "sql_injection", vulnerable=True, split="holdout")
    fp = _location("a.ts", 2, "path_traversal", vulnerable=False)
    held_path = _location("h.ts", 2, "path_traversal", vulnerable=True, split="holdout")
    fn = _location("b.ts", 3, "sql_injection", vulnerable=True)
    tn = _location("b.ts", 4, "sql_injection", vulnerable=False)
    unsupported = _location("c.ts", 5, "sql_injection", vulnerable=True)
    python = _location("v.py", 6, "code_injection", vulnerable=True, verifier="python")
    outcomes = {
        tp: LocationOutcome.VERIFIED,
        held_tp: LocationOutcome.VERIFIED,
        fp: LocationOutcome.VERIFIED,
        held_path: LocationOutcome.VERIFIED,
        fn: LocationOutcome.NOT_VERIFIED,
        tn: LocationOutcome.NOT_VERIFIED,
        python: LocationOutcome.VERIFIED,
    }
    metrics = {
        m.key: m
        for m in verifier_metrics(
            [tp, held_tp, fp, held_path, fn, tn, unsupported, python],
            outcomes,
            precision_floor=0.9,
            min_true_positives=1,
        )
    }
    sql = metrics["fdai.verify.js.sql-injection"]
    dev = sql.dev
    assert (dev.true_positives, dev.false_negatives, dev.true_negatives, dev.unsupported) == (
        1,
        1,
        1,
        1,
    )
    assert dev.precision == 1.0 and dev.recall == 0.5
    assert sql.holdout.true_positives == 1 and sql.holdout.precision == 1.0 and sql.promoted
    path = metrics["fdai.verify.js.path-traversal"]
    assert path.dev.precision == 0.0 and path.holdout.precision == 1.0 and not path.promoted
    only_dev = metrics["python:code_injection"]
    assert only_dev.dev.precision == 1.0 and only_dev.holdout.precision is None
    assert not only_dev.promoted
    assert promoted_keys(metrics.values()) == {"fdai.verify.js.sql-injection"}
    assert sql.as_dict()["holdout"] == sql.holdout.as_dict()


def test_whole_file_expected_results_expand_with_a_stable_hash_split() -> None:
    spec = ExpectedResults(
        "bench",
        "expected.csv",
        "src/{test}.java",
        "taint",
        {"sqli": "sql_injection", "cmdi": "command_injection"},
        "hash",
    )
    text = (
        "# test name, category, real vulnerability, cwe\n"
        "Test00001,sqli,true,89\nTest00002,cmdi,false,78\nTest00003,xss,true,79\n"
    )
    locations = spec.expand(text)
    assert [(item.path, item.line, item.vulnerable) for item in locations] == [
        ("src/Test00001.java", None, True),
        ("src/Test00002.java", None, False),
    ]
    assert {item.split for item in spec.expand(text)} <= {"dev", "holdout"}
    assert spec.expand(text) == locations
    assert spec.keys == {"fdai.verify.java.sql-injection", "fdai.verify.java.command-injection"}
    with pytest.raises(VerifierCorpusError, match="duplicate test"):
        spec.expand(text + "Test00001,sqli,false,89\n")
    with pytest.raises(VerifierCorpusError, match="matched no category"):
        spec.expand("Test00009,xss,true,79\n")


def test_shipped_corpus_parses_with_both_labels_and_both_splits() -> None:
    corpus = load_verifier_corpus(_raw())
    assert corpus.precision_floor == 0.9 and corpus.min_true_positives >= 1
    assert any(item.vulnerable for item in corpus.locations)
    assert any(not item.vulnerable for item in corpus.locations)
    assert {item.verifier for item in corpus.locations} == {"python", "taint"}
    assert {item.split for item in corpus.locations} == {"dev", "holdout"}
    assert {spec.split for spec in corpus.expected_results} == {"hash"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(provenance="synthetic"), "curated"),
        (lambda raw: raw.update(precision_floor=1.5), "precision_floor"),
        (lambda raw: raw["sources"][0].update(commit="main"), "40-character"),
        (lambda raw: raw["sources"][0]["locations"][0].update(label="maybe"), "bad label"),
        (lambda raw: raw["sources"][1]["locations"][2].pop("reason"), "need a reason"),
        (lambda raw: raw["sources"][0]["locations"][0].update(path="x.go"), "no taint rule"),
        (lambda raw: raw["sources"][0].pop("split"), "split must be one of"),
        (lambda raw: raw["sources"][0]["locations"][0].update(split="test"), "split must be"),
        (lambda raw: raw["sources"][0].update(id=raw["sources"][1]["id"]), "duplicate source"),
        (
            lambda raw: raw["sources"][-1]["locations"][0].update(path="x.java"),
            "python verifier",
        ),
        (
            lambda raw: raw["sources"][0]["locations"].append(
                copy.deepcopy(raw["sources"][0]["locations"][0])
            ),
            "duplicate",
        ),
    ],
)
def test_malformed_verifier_corpus_is_rejected(mutate: Any, message: str) -> None:
    raw = _raw()
    raw["sources"].append(copy.deepcopy(next(s for s in raw["sources"] if s["id"] == "pygoat")))
    raw["sources"][-1]["id"] = "pygoat-copy"
    mutate(raw)
    with pytest.raises(VerifierCorpusError, match=message):
        load_verifier_corpus(raw)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"path_template": "src/Test.java"}, "path_template"),
        ({"file": "../expected.csv"}, "path_template"),
        ({"split": "sometimes"}, "split must be one of"),
        ({"categories": {}}, "categories"),
        ({"categories": {"sqli": "sql_injection"}, "verifier": "python"}, "python verifier"),
    ],
)
def test_malformed_expected_results_are_rejected(change: dict[str, Any], message: str) -> None:
    raw = _raw()
    source = next(s for s in raw["sources"] if "expected_results" in s)
    source["expected_results"].update(change)
    with pytest.raises(VerifierCorpusError, match=message):
        load_verifier_corpus(raw)
