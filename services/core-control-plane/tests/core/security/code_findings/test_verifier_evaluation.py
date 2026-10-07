"""Tests for verifier precision metrics and the real-code verifier corpus format."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from fdai.core.security.code_findings.verifier_evaluation import (
    LabeledLocation,
    LocationOutcome,
    VerifierCorpusError,
    locations_from_mapping,
    promoted_keys,
    verifier_metrics,
)

from ._support import CATALOG_ROOT


def _raw() -> dict[str, Any]:
    return yaml.safe_load(  # type: ignore[no-any-return]
        (CATALOG_ROOT / "evaluation" / "verifier-corpus.yaml").read_text(encoding="utf-8")
    )


def _location(
    path: str, line: int, cls: str, *, vulnerable: bool, verifier: str = "taint"
) -> LabeledLocation:
    return LabeledLocation("s", path, line, cls, verifier, vulnerable)


def test_metrics_count_outcomes_and_gate_promotion() -> None:
    tp = _location("a.ts", 1, "sql_injection", vulnerable=True)
    fp = _location("a.ts", 2, "path_traversal", vulnerable=False)
    fn = _location("b.ts", 3, "sql_injection", vulnerable=True)
    tn = _location("b.ts", 4, "sql_injection", vulnerable=False)
    unsupported = _location("c.ts", 5, "sql_injection", vulnerable=True)
    python = _location("v.py", 6, "code_injection", vulnerable=True, verifier="python")
    outcomes = {
        tp: LocationOutcome.VERIFIED,
        fp: LocationOutcome.VERIFIED,
        fn: LocationOutcome.NOT_VERIFIED,
        tn: LocationOutcome.NOT_VERIFIED,
        python: LocationOutcome.VERIFIED,
    }
    metrics = {
        m.key: m
        for m in verifier_metrics(
            [tp, fp, fn, tn, unsupported, python],
            outcomes,
            precision_floor=0.9,
            min_true_positives=1,
        )
    }
    sql = metrics["fdai.verify.js.sql-injection"]
    assert (sql.true_positives, sql.false_negatives, sql.true_negatives, sql.unsupported) == (
        1,
        1,
        1,
        1,
    )
    assert sql.precision == 1.0 and sql.recall == 0.5 and sql.promoted
    path = metrics["fdai.verify.js.path-traversal"]
    assert path.precision == 0.0 and not path.promoted
    assert promoted_keys(metrics.values()) == {
        "fdai.verify.js.sql-injection",
        "python:code_injection",
    }


def test_shipped_corpus_parses_with_both_labels() -> None:
    header, locations = locations_from_mapping(_raw())
    assert header["precision_floor"] == 0.9
    assert any(item.vulnerable for item in locations)
    assert any(not item.vulnerable for item in locations)
    assert {item.verifier for item in locations} == {"python", "taint"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(provenance="synthetic"), "curated"),
        (lambda raw: raw.update(precision_floor=1.5), "precision_floor"),
        (lambda raw: raw["sources"][0].update(commit="main"), "40-character"),
        (lambda raw: raw["sources"][0]["locations"][0].update(label="maybe"), "bad label"),
        (lambda raw: raw["sources"][1]["locations"][2].pop("reason"), "need a reason"),
        (lambda raw: raw["sources"][0]["locations"][0].update(path="x.go"), "no taint rule"),
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
    mutate(raw)
    with pytest.raises(VerifierCorpusError, match=message):
        locations_from_mapping(raw)
