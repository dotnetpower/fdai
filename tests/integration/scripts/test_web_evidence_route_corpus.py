"""The frozen web-evidence route corpus keeps its bilingual acceptance contract."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.evaluation.web_evidence_route_corpus import (
    CorpusError,
    Intent,
    Locale,
    Route,
    load_corpus,
    main,
    parse_corpus,
    summary,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "tests/integration/evaluation/web_evidence_route_corpus.v1.json"


def _raw() -> dict[str, Any]:
    return json.loads(_CORPUS.read_text(encoding="utf-8"))


def _case(raw: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in raw["cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def test_frozen_corpus_loads_with_balanced_bilingual_coverage() -> None:
    corpus = load_corpus(_CORPUS)

    assert corpus.corpus_version == "v1"
    assert len(corpus.cases) == 10
    assert sum(1 for case in corpus.cases if case.locale is Locale.EN) == 5
    assert sum(1 for case in corpus.cases if case.locale is Locale.KO) == 5
    assert {case.expected_route for case in corpus.cases} == set(Route)


def test_every_documented_intent_is_present() -> None:
    corpus = load_corpus(_CORPUS)

    assert {case.intent for case in corpus.cases} >= {
        Intent.EXPLICIT_WEB,
        Intent.COLLOQUIAL_WEB,
        Intent.FRESHNESS,
        Intent.ALTERNATIVE_DISCOVERY,
        Intent.LOCAL_SCOPE,
        Intent.CURRENT_SCREEN,
        Intent.SENSITIVE,
        Intent.NO_SEARCH,
    }


def test_provider_call_is_expected_only_for_an_undenied_web_route() -> None:
    for case in load_corpus(_CORPUS).cases:
        allowed = case.expected_route is Route.WEB and case.expected_denial_reason is None
        assert case.expects_provider_call is allowed
        assert (case.expected_normalized_query is not None) is allowed


def test_sensitive_and_screen_cases_never_reach_a_provider() -> None:
    corpus = load_corpus(_CORPUS)
    guarded = [
        case
        for case in corpus.cases
        if case.intent in {Intent.SENSITIVE, Intent.CURRENT_SCREEN, Intent.LOCAL_SCOPE}
    ]

    assert guarded
    for case in guarded:
        assert case.expected_route is not Route.WEB
        assert case.expects_provider_call is False


def test_normalized_queries_stay_bounded_ascii_for_both_locales() -> None:
    for case in load_corpus(_CORPUS).cases:
        query = case.expected_normalized_query
        if query is None:
            continue
        assert query.isascii()
        assert query == query.lower()
        assert len(query) <= 120


def test_korean_and_english_prompts_use_their_declared_language() -> None:
    for case in load_corpus(_CORPUS).cases:
        if case.locale is Locale.EN:
            assert case.prompt.isascii()
        else:
            assert any("가" <= char <= "힣" for char in case.prompt)


def test_summary_is_content_free() -> None:
    result = summary(load_corpus(_CORPUS))

    assert result["case_count"] == 10
    assert result["locales"] == {"en": 5, "ko": 5}
    rendered = json.dumps(result, ensure_ascii=False)
    for case in load_corpus(_CORPUS).cases:
        assert case.prompt not in rendered


def test_unknown_fields_are_rejected() -> None:
    raw = _raw()
    raw["unexpected"] = True

    with pytest.raises(CorpusError, match="unknown fields"):
        parse_corpus(raw)


def test_a_web_route_cannot_drop_its_provider_call_expectation() -> None:
    raw = _raw()
    _case(raw, "en-explicit-web")["expects_provider_call"] = False

    with pytest.raises(CorpusError, match="contradicts its route"):
        parse_corpus(raw)


def test_a_sensitive_case_cannot_become_a_web_route() -> None:
    raw = _raw()
    case = _case(raw, "en-sensitive")
    case["expected_route"] = "web"
    case["expects_provider_call"] = True
    case["expected_normalized_query"] = "subscription owner"
    case["expected_denial_reason"] = None

    with pytest.raises(CorpusError, match="deny sensitive retrieval"):
        parse_corpus(raw)


def test_alternative_discovery_keeps_its_distinct_product_floor() -> None:
    raw = _raw()
    _case(raw, "en-alternative-discovery")["expected_min_distinct_products"] = 2

    with pytest.raises(CorpusError, match="distinct products"):
        parse_corpus(raw)


def test_locale_balance_is_enforced() -> None:
    raw = _raw()
    duplicate = deepcopy(_case(raw, "en-local-scope"))
    duplicate["id"] = "en-local-scope-2"
    duplicate["prompt"] = "List the stopped db instances in the shared platform scope."
    raw["cases"] = [case for case in raw["cases"] if case["id"] != "ko-no-search"]
    raw["cases"].append(duplicate)

    with pytest.raises(CorpusError, match="MUST contain 5"):
        parse_corpus(raw)


def test_a_korean_case_cannot_hold_english_only_text() -> None:
    raw = _raw()
    _case(raw, "ko-explicit-web")["prompt"] = "Search the web for upgrade guidance."

    with pytest.raises(CorpusError, match="Korean text"):
        parse_corpus(raw)


def test_schema_version_is_pinned() -> None:
    raw = _raw()
    raw["schema_version"] = 2

    with pytest.raises(CorpusError, match="schema_version"):
        parse_corpus(raw)


def test_cli_reports_the_coverage_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--corpus", str(_CORPUS)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["corpus_id"] == "web-evidence-route-corpus"
    assert payload["provider_call_cases"] == 5


def test_cli_fails_a_broken_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "corpus.json"
    raw = _raw()
    raw["cases"] = raw["cases"][:3]
    broken.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    assert main(["--corpus", str(broken)]) == 1
    assert "FAIL" in capsys.readouterr().err
