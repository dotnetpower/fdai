#!/usr/bin/env python3
"""Load and validate the frozen web-evidence route and provider-call corpus.

The corpus is the acceptance contract for operator console public web evidence:
each case declares the expected structured route (`web`, `local`, or `none`),
whether a search provider call is allowed, the normalized English query a `web`
case must produce, and the sensitive, current-screen, and alternative-discovery
expectations described in
`docs/roadmap/interfaces/operator-console-web-evidence.md`.

This module owns only the corpus contract. It performs no routing, calls no
provider, and grants no execution authority. A future Operator suite consumes
`load_corpus()` and compares its own route and provider-call observations with
these frozen expectations.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

_ID = re.compile(r"^(en|ko)-[a-z0-9][a-z0-9-]{0,47}$")
_NORMALIZED_QUERY = re.compile(r"^[a-z0-9][a-z0-9 .+-]{2,119}$")
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_CASE_KEYS = frozenset(
    {
        "id",
        "locale",
        "intent",
        "prompt",
        "expected_route",
        "expects_provider_call",
        "expected_normalized_query",
        "expected_alternative_discovery",
        "expected_min_distinct_products",
        "expected_denial_reason",
    }
)
_ROOT_KEYS = frozenset({"schema_version", "corpus_id", "corpus_version", "description", "cases"})
_SCHEMA_VERSION = 1
_CORPUS_ID = "web-evidence-route-corpus"
_CASE_COUNT = 10
_CASES_PER_LOCALE = 5
_MIN_ALTERNATIVE_PRODUCTS = 3
_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/integration/evaluation/web_evidence_route_corpus.v1.json"
)


class Locale(StrEnum):
    EN = "en"
    KO = "ko"


class Route(StrEnum):
    WEB = "web"
    LOCAL = "local"
    NONE = "none"


class Intent(StrEnum):
    EXPLICIT_WEB = "explicit_web"
    COLLOQUIAL_WEB = "colloquial_web"
    FRESHNESS = "freshness"
    ALTERNATIVE_DISCOVERY = "alternative_discovery"
    LOCAL_SCOPE = "local_scope"
    CURRENT_SCREEN = "current_screen"
    SENSITIVE = "sensitive"
    NO_SEARCH = "no_search"


class DenialReason(StrEnum):
    SENSITIVE_INPUT = "sensitive_input"


_REQUIRED_INTENTS = frozenset(
    {
        Intent.EXPLICIT_WEB,
        Intent.COLLOQUIAL_WEB,
        Intent.FRESHNESS,
        Intent.ALTERNATIVE_DISCOVERY,
        Intent.LOCAL_SCOPE,
        Intent.CURRENT_SCREEN,
        Intent.SENSITIVE,
        Intent.NO_SEARCH,
    }
)


class CorpusError(ValueError):
    """One frozen corpus document failed its contract."""


@dataclass(frozen=True, slots=True)
class RouteCase:
    """One frozen route expectation. Every field is an expectation, not a result."""

    id: str
    locale: Locale
    intent: Intent
    prompt: str
    expected_route: Route
    expects_provider_call: bool
    expected_normalized_query: str | None
    expected_alternative_discovery: bool
    expected_min_distinct_products: int | None
    expected_denial_reason: DenialReason | None


@dataclass(frozen=True, slots=True)
class RouteCorpus:
    corpus_id: str
    corpus_version: str
    cases: tuple[RouteCase, ...]


def load_corpus(path: Path | None = None) -> RouteCorpus:
    """Return the validated corpus, or raise `CorpusError` for any violation."""

    source = path if path is not None else _DEFAULT_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CorpusError("web evidence corpus is unreadable") from exc
    except json.JSONDecodeError as exc:
        raise CorpusError("web evidence corpus is not valid JSON") from exc
    return parse_corpus(raw)


def parse_corpus(raw: Any) -> RouteCorpus:
    if not isinstance(raw, dict):
        raise CorpusError("web evidence corpus root MUST be an object")
    unknown = set(raw) - _ROOT_KEYS
    if unknown:
        raise CorpusError("web evidence corpus has unknown fields: " + ", ".join(sorted(unknown)))
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise CorpusError("web evidence corpus schema_version MUST be 1")
    if raw.get("corpus_id") != _CORPUS_ID:
        raise CorpusError(f"web evidence corpus_id MUST be {_CORPUS_ID}")
    version = raw.get("corpus_version")
    if not isinstance(version, str) or not re.fullmatch(r"v[0-9]+", version):
        raise CorpusError("web evidence corpus_version MUST look like v1")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list):
        raise CorpusError("web evidence corpus cases MUST be an array")
    cases = tuple(_case(value) for value in raw_cases)
    _validate_coverage(cases)
    return RouteCorpus(corpus_id=_CORPUS_ID, corpus_version=version, cases=cases)


def _case(raw: Any) -> RouteCase:
    if not isinstance(raw, dict):
        raise CorpusError("web evidence corpus case MUST be an object")
    missing = _CASE_KEYS - set(raw)
    if missing:
        raise CorpusError("web evidence case is missing fields: " + ", ".join(sorted(missing)))
    unknown = set(raw) - _CASE_KEYS
    if unknown:
        raise CorpusError("web evidence case has unknown fields: " + ", ".join(sorted(unknown)))
    case_id = raw["id"]
    if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
        raise CorpusError("web evidence case id MUST be a bounded locale-prefixed token")
    locale = Locale(_string(raw, "locale"))
    if not case_id.startswith(f"{locale.value}-"):
        raise CorpusError(f"web evidence case {case_id} id MUST match its locale")
    prompt = raw["prompt"]
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 240:
        raise CorpusError(f"web evidence case {case_id} prompt MUST be 1-240 characters")
    if locale is Locale.KO and not _HANGUL.search(prompt):
        raise CorpusError(f"web evidence case {case_id} MUST contain Korean text")
    if locale is Locale.EN and not prompt.isascii():
        raise CorpusError(f"web evidence case {case_id} MUST contain ASCII English text")
    normalized = raw["expected_normalized_query"]
    if normalized is not None and (
        not isinstance(normalized, str) or not _NORMALIZED_QUERY.fullmatch(normalized)
    ):
        raise CorpusError(
            f"web evidence case {case_id} normalized query MUST be a bounded ASCII query"
        )
    products = raw["expected_min_distinct_products"]
    if products is not None and (not isinstance(products, int) or isinstance(products, bool)):
        raise CorpusError(f"web evidence case {case_id} distinct product floor MUST be an integer")
    denial = raw["expected_denial_reason"]
    if denial is not None and not isinstance(denial, str):
        raise CorpusError(f"web evidence case {case_id} denial reason MUST be a string or null")
    case = RouteCase(
        id=case_id,
        locale=locale,
        intent=Intent(_string(raw, "intent")),
        prompt=prompt,
        expected_route=Route(_string(raw, "expected_route")),
        expects_provider_call=_boolean(raw, "expects_provider_call", case_id),
        expected_normalized_query=normalized,
        expected_alternative_discovery=_boolean(raw, "expected_alternative_discovery", case_id),
        expected_min_distinct_products=products,
        expected_denial_reason=None if denial is None else DenialReason(denial),
    )
    _validate_case(case)
    return case


def _validate_case(case: RouteCase) -> None:
    provider_allowed = case.expected_route is Route.WEB and case.expected_denial_reason is None
    if case.expects_provider_call != provider_allowed:
        raise CorpusError(
            f"web evidence case {case.id} provider-call expectation contradicts its route"
        )
    if case.expects_provider_call and case.expected_normalized_query is None:
        raise CorpusError(f"web evidence case {case.id} MUST declare a normalized query")
    if not case.expects_provider_call and case.expected_normalized_query is not None:
        raise CorpusError(
            f"web evidence case {case.id} MUST NOT declare a query without a provider call"
        )
    if case.intent is Intent.SENSITIVE:
        if case.expected_route is Route.WEB or case.expected_denial_reason is None:
            raise CorpusError(f"web evidence case {case.id} MUST deny sensitive retrieval")
    elif case.expected_denial_reason is not None:
        raise CorpusError(f"web evidence case {case.id} MUST NOT declare a denial reason")
    if case.intent is Intent.CURRENT_SCREEN and case.expected_route is not Route.LOCAL:
        raise CorpusError(f"web evidence case {case.id} MUST keep a screen question local")
    if case.intent is Intent.LOCAL_SCOPE and case.expected_route is not Route.LOCAL:
        raise CorpusError(f"web evidence case {case.id} MUST keep a local scope question local")
    if case.expected_alternative_discovery != (case.intent is Intent.ALTERNATIVE_DISCOVERY):
        raise CorpusError(
            f"web evidence case {case.id} alternative-discovery flag contradicts its intent"
        )
    if case.expected_alternative_discovery:
        if (
            case.expected_min_distinct_products is None
            or case.expected_min_distinct_products < _MIN_ALTERNATIVE_PRODUCTS
        ):
            raise CorpusError(
                f"web evidence case {case.id} MUST request at least "
                f"{_MIN_ALTERNATIVE_PRODUCTS} distinct products"
            )
    elif case.expected_min_distinct_products is not None:
        raise CorpusError(
            f"web evidence case {case.id} MUST NOT declare a product floor without discovery"
        )


def _validate_coverage(cases: Sequence[RouteCase]) -> None:
    if len(cases) != _CASE_COUNT:
        raise CorpusError(f"web evidence corpus MUST contain exactly {_CASE_COUNT} cases")
    identifiers = {case.id for case in cases}
    if len(identifiers) != len(cases):
        raise CorpusError("web evidence corpus case ids MUST be unique")
    prompts = {case.prompt for case in cases}
    if len(prompts) != len(cases):
        raise CorpusError("web evidence corpus prompts MUST be unique")
    for locale in Locale:
        count = sum(1 for case in cases if case.locale is locale)
        if count != _CASES_PER_LOCALE:
            raise CorpusError(
                f"web evidence corpus MUST contain {_CASES_PER_LOCALE} {locale.value} cases"
            )
    intents = {case.intent for case in cases}
    missing = _REQUIRED_INTENTS - intents
    if missing:
        raise CorpusError(
            "web evidence corpus is missing intents: "
            + ", ".join(sorted(intent.value for intent in missing))
        )
    routes = {case.expected_route for case in cases}
    if routes != set(Route):
        raise CorpusError("web evidence corpus MUST cover the web, local, and none routes")


def _string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise CorpusError(f"web evidence case {key} MUST be a non-empty string")
    return value


def _boolean(raw: dict[str, Any], key: str, case_id: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise CorpusError(f"web evidence case {case_id} {key} MUST be a boolean")
    return value


def summary(corpus: RouteCorpus) -> dict[str, object]:
    """Return a content-free coverage summary for a review receipt."""

    return {
        "corpus_id": corpus.corpus_id,
        "corpus_version": corpus.corpus_version,
        "case_count": len(corpus.cases),
        "locales": {
            locale.value: sum(1 for case in corpus.cases if case.locale is locale)
            for locale in Locale
        },
        "routes": {
            route.value: sum(1 for case in corpus.cases if case.expected_route is route)
            for route in Route
        },
        "provider_call_cases": sum(1 for case in corpus.cases if case.expects_provider_call),
        "intents": sorted({case.intent.value for case in corpus.cases}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_PATH)
    args = parser.parse_args(argv)
    try:
        corpus = load_corpus(args.corpus)
    except CorpusError as exc:
        print(f"web-evidence-route-corpus: FAIL {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary(corpus), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
