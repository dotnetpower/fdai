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
    "|(?:\uc778\ud130\ub137|\uc6f9).{0,80}(?:\uac80\uc0c9|\ucc3e\uc544|\uc870\uc0ac)"
    "|(?:\uac80\uc0c9|\ucc3e\uc544|\uc870\uc0ac).{0,80}(?:\uc778\ud130\ub137|\uc6f9)",
    re.IGNORECASE,
)
_WEB_CONTEXT: Final = re.compile(
    r"\b(?:web|internet|online)\b|\uc778\ud130\ub137|\uc6f9|\uc628\ub77c\uc778",
    re.IGNORECASE,
)
_EXPLICIT_SEARCH_REQUEST: Final = re.compile(
    r"\b(?:search|find|look\s+up|research|discover|google|browse)\b"
    "|(?:\uac80\uc0c9|\uc870\uc0ac|\uad6c\uae00\ub9c1)\\s*(?:\ud574|\ud574\uc11c|\ud574\uc918|\ud574\ubd10|\ud574\uc904\ub798|\ud574\uc8fc\uc138\uc694|\ubd80\ud0c1)"
    "|\ucc3e\uc544\\s*(?:\ubd10|\uc918|\uc904\ub798|\uc8fc\uc138\uc694)"
    "|\uc54c\uc544\\s*(?:\ubd10|\uc918|\uc904\ub798|\uc8fc\uc138\uc694)",
    re.IGNORECASE,
)
_ALTERNATIVE_COMPARISON: Final = re.compile(
    r"\b(?:similar|comparable|alternative|competitor)s?\b"
    "|\ube44\uc2b7|\uc720\uc0ac|\ub300\uc548|\uacbd\uc7c1",
    re.IGNORECASE,
)
_PUBLIC_DISCOVERY_SUBJECT: Final = re.compile(
    r"\b(?:service|product|tool|solution|platform|alternative|competitor)s?\b"
    "|\uc11c\ube44\uc2a4|\uc81c\ud488|\ub3c4\uad6c|\uc194\ub8e8\uc158|\ud50c\ub7ab\ud3fc|\ub300\uc548|\uacbd\uc7c1",
    re.IGNORECASE,
)
_LOCAL_SEARCH_SCOPE: Final = re.compile(
    r"\b(?:this|current)\s+(?:screen|page|table|list|view)\b"
    r"|\b(?:audit|activity)\s+logs?\b"
    r"|\b(?:in|from|within)\s+(?:the\s+)?(?:inventory|catalog|database|db)\b"
    "|(?:\uc774|\ud604\uc7ac)\\s*(?:\ud654\uba74|\ud398\uc774\uc9c0|\ud45c|\ubaa9\ub85d|\ubdf0)"
    "|(?:\uac10\uc0ac|\ud65c\ub3d9)\\s*\ub85c\uadf8"
    "|(?:\uc778\ubca4\ud1a0\ub9ac|\uce74\ud0c8\ub85c\uadf8|\ub370\uc774\ud130\ubca0\uc774\uc2a4|\ub514\ube44)(?:\uc5d0\uc11c|\\s*\uc548\uc5d0\uc11c|\\s*\ub0b4\uc5d0\uc11c)",
    re.IGNORECASE,
)
_FRESHNESS: Final = re.compile(
    r"\b(?:latest|newest|today|recent|currently|now|trending|current\s+(?:release|version)"
    r"|recently\s+released|as\s+of\s+today|release\s+notes?)\b"
    "|\ucd5c\uc2e0|\uc624\ub298|\uc694\uc998|\ucd5c\uadfc|\uc9c0\uae08|\ud604\uc7ac\\s*\ubc84\uc804"
    "|\ucd5c\uadfc\\s*\ubc1c\ud45c|\ub9b4\ub9ac\uc2a4\\s*\ub178\ud2b8",
    re.IGNORECASE,
)
_PUBLIC_SUBJECT: Final = re.compile(
    r"\b(?:azure|microsoft|foundry|openai|python|kubernetes|aks|postgres(?:ql)?"
    r"|cve|nvd|rfc|sdk|api|documentation|docs?|release|version|package|library)\b"
    "|\uacf5\uc2dd\\s*\ubb38\uc11c|\ubcf4\uc548\\s*\uacf5\uc9c0|\ucde8\uc57d\uc810|\ubc84\uc804|\ub9b4\ub9ac\uc2a4",
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
