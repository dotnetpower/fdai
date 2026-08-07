"""Structured T0 and semantic search-intent decisions for console chat."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Literal, NamedTuple, cast

SearchGoal = Literal["alternatives", "current_fact", "research", "local", "none"]


class SearchIntentDecision(NamedTuple):
    route: Literal["web", "local", "none"]
    confidence: float
    reason: str
    query: str
    goal: SearchGoal
    subject: str
    capabilities: tuple[str, ...]


_EXPLICIT_WEB_SEARCH: Final = re.compile(
    r"\b(?:search|browse)\s+(?:the\s+)?(?:web|internet|online)\b"
    r"|\b(?:web|internet)\s+search\b"
    "|(?:인터넷|웹).{0,80}(?:검색|찾아|조사)"
    "|(?:검색|찾아|조사).{0,80}(?:인터넷|웹)",
    re.IGNORECASE,
)
_WEB_CONTEXT: Final = re.compile(
    r"\b(?:web|internet|online)\b|인터넷|웹|온라인",
    re.IGNORECASE,
)
_EXPLICIT_SEARCH_REQUEST: Final = re.compile(
    r"\b(?:search|find|look\s+up|research|discover|google|browse)\b"
    "|(?:검색|조사|구글링)\\s*(?:해|해서|해줘|해봐|해줄래|해주세요|부탁)"
    "|찾아\\s*(?:봐|줘|줄래|주세요)"
    "|알아\\s*(?:봐|줘|줄래|주세요)",
    re.IGNORECASE,
)
_ALTERNATIVE_COMPARISON: Final = re.compile(
    r"\b(?:similar|comparable|alternative|competitor)s?\b"
    "|비슷|유사|대안|경쟁",
    re.IGNORECASE,
)
_PUBLIC_DISCOVERY_SUBJECT: Final = re.compile(
    r"\b(?:service|product|tool|solution|platform|alternative|competitor)s?\b"
    "|서비스|제품|도구|솔루션|플랫폼|대안|경쟁",
    re.IGNORECASE,
)
_LOCAL_SEARCH_SCOPE: Final = re.compile(
    r"\b(?:this|current)\s+(?:screen|page|table|list|view)\b"
    r"|\b(?:audit|activity)\s+logs?\b"
    r"|\b(?:in|from|within)\s+(?:the\s+)?(?:inventory|catalog|database|db)\b"
    "|(?:이|현재)\\s*(?:화면|페이지|표|목록|뷰)"
    "|(?:감사|활동)\\s*로그"
    "|(?:인벤토리|카탈로그|데이터베이스|디비)(?:에서|\\s*안에서|\\s*내에서)",
    re.IGNORECASE,
)
_FRESHNESS: Final = re.compile(
    r"\b(?:latest|newest|today|recent|currently|now|trending|current\s+(?:release|version)"
    r"|recently\s+released|as\s+of\s+today|release\s+notes?)\b"
    "|최신|오늘|요즘|최근|지금|현재\\s*버전"
    "|최근\\s*발표|릴리스\\s*노트",
    re.IGNORECASE,
)
_PUBLIC_SUBJECT: Final = re.compile(
    r"\b(?:azure|microsoft|foundry|openai|python|kubernetes|aks|postgres(?:ql)?"
    r"|cve|nvd|rfc|sdk|api|documentation|docs?|release|version|package|library)\b"
    "|공식\\s*문서|보안\\s*공지|취약점|버전|릴리스",
    re.IGNORECASE,
)
_SEMANTIC_INTENTS: Final = frozenset({"open_question", "list", "comparison", "proposal", "status"})


def classify_search_intent(prompt: str) -> SearchIntentDecision:
    if _EXPLICIT_WEB_SEARCH.search(prompt):
        return SearchIntentDecision("web", 1.0, "explicit_web_search", prompt, "research", "", ())
    search_requested = _EXPLICIT_SEARCH_REQUEST.search(prompt) is not None
    if _WEB_CONTEXT.search(prompt) and (
        search_requested or _PUBLIC_DISCOVERY_SUBJECT.search(prompt)
    ):
        return SearchIntentDecision("web", 1.0, "explicit_web_context", prompt, "research", "", ())
    if search_requested and _LOCAL_SEARCH_SCOPE.search(prompt):
        return SearchIntentDecision("local", 1.0, "explicit_local_scope", "", "local", "", ())
    if search_requested:
        return SearchIntentDecision(
            "web", 1.0, "explicit_search_request", prompt, "research", "", ()
        )
    if _FRESHNESS.search(prompt) and (
        _PUBLIC_SUBJECT.search(prompt) or _PUBLIC_DISCOVERY_SUBJECT.search(prompt)
    ):
        return SearchIntentDecision(
            "web", 0.8, "fresh_public_subject", prompt, "current_fact", "", ()
        )
    return SearchIntentDecision("none", 1.0, "no_search_intent", "", "none", "", ())


def semantic_search_intent_eligible(view_context: Mapping[str, object]) -> bool:
    plan = view_context.get("_answer_plan")
    return isinstance(plan, Mapping) and plan.get("intent") in _SEMANTIC_INTENTS


def alternative_search_requested(prompt: str) -> bool:
    return _ALTERNATIVE_COMPARISON.search(prompt) is not None


def semantic_search_intent(raw: Mapping[str, object]) -> SearchIntentDecision:
    route = raw.get("route")
    confidence = raw.get("confidence")
    reason = raw.get("reason")
    query = raw.get("query")
    goal = raw.get("goal")
    subject = raw.get("subject")
    capabilities = raw.get("capabilities")
    if (
        route not in {"web", "local", "none"}
        or not isinstance(confidence, int | float)
        or isinstance(confidence, bool)
        or not 0.0 <= float(confidence) <= 1.0
        or not isinstance(reason, str)
        or not reason
        or len(reason) > 64
        or not isinstance(query, str)
        or len(query) > 1000
        or (route == "web" and not query.strip())
        or goal not in {"alternatives", "current_fact", "research", "local", "none"}
        or not isinstance(subject, str)
        or len(subject) > 128
        or (goal == "alternatives" and not subject.strip())
        or not isinstance(capabilities, list)
        or len(capabilities) > 8
        or any(
            not isinstance(capability, str) or not capability.strip() or len(capability) > 64
            for capability in capabilities
        )
        or (goal == "alternatives" and len(capabilities) < 2)
        or (goal != "alternatives" and capabilities)
    ):
        return SearchIntentDecision("none", 1.0, "semantic_invalid", "", "none", "", ())
    if float(confidence) < 0.7:
        return SearchIntentDecision("none", 1.0, "semantic_low_confidence", "", "none", "", ())
    typed_route = cast(Literal["web", "local", "none"], route)
    typed_goal = cast(SearchGoal, goal)
    normalized_capabilities = tuple(
        dict.fromkeys(capability.strip() for capability in capabilities)
    )
    normalized_query = query.strip() if typed_route == "web" else ""
    if typed_goal == "alternatives":
        normalized_query = f"{' '.join(normalized_capabilities)} AIOps platforms products"
    return SearchIntentDecision(
        typed_route,
        float(confidence),
        f"semantic:{reason}",
        normalized_query,
        typed_goal,
        subject.strip() if typed_goal == "alternatives" else "",
        normalized_capabilities,
    )


__all__ = [
    "SearchIntentDecision",
    "SearchGoal",
    "alternative_search_requested",
    "classify_search_intent",
    "semantic_search_intent",
    "semantic_search_intent_eligible",
]
