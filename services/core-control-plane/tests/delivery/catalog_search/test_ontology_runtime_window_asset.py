"""Frozen runtime shadow window cases: shape, corpus labels, and disjointness."""

from collections import Counter

from tests.delivery.catalog_search.test_ontology_evaluation_assets import (
    _corpus_document_ids,
    _load_asset,
    _normalized_query,
)

_WINDOW = "instance-runtime-window.v1.json"
_GOVERNED_WINDOW = "governed-read-window.v1.json"
_GOVERNED_WINDOW_V2 = "governed-read-window.v2.json"
_GOVERNED_WINDOW_V3 = "governed-read-window.v3.json"
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
_GOVERNED_PRIOR = (*_PRIOR, _WINDOW)
_GOVERNED_V2_PRIOR = (*_GOVERNED_PRIOR, _GOVERNED_WINDOW)
_GOVERNED_V3_PRIOR = (*_GOVERNED_V2_PRIOR, _GOVERNED_WINDOW_V2)


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


def test_governed_window_has_frozen_shape_and_corpus_labels() -> None:
    window = _load_asset(_GOVERNED_WINDOW)
    cases = window["cases"]
    assert window["independently_reviewed"] is True
    assert window["production_qualification"] is False
    assert window["corpus"] == "instance-corpus.v1.json"
    assert Counter(item["cohort"] for item in cases) == _COHORTS
    assert {item["case_id"] for item in cases} == {
        f"governed1-{language}-{index:02d}" for language in ("en", "ko") for index in range(1, 33)
    }
    object_ids = _corpus_document_ids()
    assert all(set(item["expected_document_ids"]) <= object_ids for item in cases)


def test_governed_window_queries_are_disjoint_from_every_spent_set() -> None:
    queries = {_normalized_query(item["query"]) for item in _load_asset(_GOVERNED_WINDOW)["cases"]}
    spent = {
        _normalized_query(item["query"])
        for asset in _GOVERNED_PRIOR
        for item in _load_asset(asset)["cases"]
    }
    assert len(queries) == 64
    assert queries.isdisjoint(spent)


def test_governed_v2_window_is_fresh_reviewed_and_disjoint() -> None:
    window = _load_asset(_GOVERNED_WINDOW_V2)
    cases = window["cases"]
    assert window["independently_reviewed"] is True
    assert window["production_qualification"] is False
    assert window["supersedes"] == _GOVERNED_WINDOW
    assert Counter(item["cohort"] for item in cases) == _COHORTS
    assert {item["case_id"] for item in cases} == {
        f"governed2-{language}-{index:02d}" for language in ("en", "ko") for index in range(1, 33)
    }
    object_ids = _corpus_document_ids()
    assert all(set(item["expected_document_ids"]) <= object_ids for item in cases)
    queries = {_normalized_query(item["query"]) for item in cases}
    spent = {
        _normalized_query(item["query"])
        for asset in _GOVERNED_V2_PRIOR
        for item in _load_asset(asset)["cases"]
    }
    assert len(queries) == 64
    assert queries.isdisjoint(spent)


def test_governed_v3_window_is_fresh_reviewed_and_disjoint() -> None:
    window = _load_asset(_GOVERNED_WINDOW_V3)
    cases = window["cases"]
    assert window["independently_reviewed"] is True
    assert window["production_qualification"] is False
    assert window["supersedes"] == _GOVERNED_WINDOW_V2
    assert Counter(item["cohort"] for item in cases) == _COHORTS
    assert {item["case_id"] for item in cases} == {
        f"governed3-{language}-{index:02d}" for language in ("en", "ko") for index in range(1, 33)
    }
    object_ids = _corpus_document_ids()
    multi = Counter()
    for case in cases:
        expected = case["expected_document_ids"]
        assert expected == sorted(set(expected))
        assert set(expected) <= object_ids
        if case["cohort"].endswith("-positive"):
            assert expected
            multi[case["cohort"]] += len(expected) > 1
        else:
            assert expected == []
    assert all(multi[f"{language}-positive"] >= 5 for language in ("en", "ko"))
    queries = {_normalized_query(item["query"]) for item in cases}
    spent = {
        _normalized_query(item["query"])
        for asset in _GOVERNED_V3_PRIOR
        for item in _load_asset(asset)["cases"]
    }
    assert len(queries) == 64
    assert queries.isdisjoint(spent)
