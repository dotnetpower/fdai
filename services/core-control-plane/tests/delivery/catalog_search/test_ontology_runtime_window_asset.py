"""Frozen runtime shadow window cases: shape, corpus labels, and disjointness."""

from collections import Counter

from tests.delivery.catalog_search.test_ontology_evaluation_assets import (
    _corpus_document_ids,
    _load_asset,
    _normalized_query,
)

_WINDOW = "instance-runtime-window.v1.json"
_COHORTS = {
    f"{language}-{cohort}": count
    for language in ("en", "ko")
    for cohort, count in (("positive", 16), ("ambiguous", 8), ("negative", 4), ("adversarial", 4))
}
_PRIOR = (
    "instance-calibration.v1.json",
    "instance-calibration.v2.json",
    "instance-calibration.v3.json",
    "instance-holdout.v1.json",
    "instance-holdout.v2.json",
    "instance-holdout.v3.json",
    "instance-holdout.v4.json",
    "instance-holdout.v5a.json",
    "instance-holdout.v5b.json",
)


def test_runtime_window_has_frozen_shape_and_cohorts() -> None:
    window = _load_asset(_WINDOW)
    calibration = _load_asset("instance-calibration.v3.json")
    cases = window["cases"]
    assert window["independently_reviewed"] is True
    assert window["production_qualification"] is False
    assert window["corpus"] == "instance-corpus.v1.json"
    assert window["evaluation_policy"] == calibration["evaluation_policy"]
    assert Counter(item["cohort"] for item in cases) == _COHORTS
    assert {item["case_id"] for item in cases} == {
        f"window1-{language}-{index:02d}" for language in ("en", "ko") for index in range(1, 33)
    }


def test_runtime_window_labels_reference_only_corpus_identities() -> None:
    object_ids = _corpus_document_ids()
    multi = Counter()
    for case in _load_asset(_WINDOW)["cases"]:
        expected = case["expected_document_ids"]
        assert expected == sorted(set(expected))
        assert set(expected) <= object_ids
        if case["cohort"].endswith("-positive"):
            assert expected
            multi[case["cohort"]] += len(expected) > 1
        else:
            assert expected == []
    assert all(multi[f"{language}-positive"] >= 5 for language in ("en", "ko"))


def test_runtime_window_queries_are_disjoint_from_every_spent_set() -> None:
    queries = {_normalized_query(item["query"]) for item in _load_asset(_WINDOW)["cases"]}
    prior = {
        _normalized_query(item["query"]) for asset in _PRIOR for item in _load_asset(asset)["cases"]
    }
    assert len(queries) == 64
    assert queries.isdisjoint(prior)
