"""Parse Azure Responses web-search output into replayable snippets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fdai.core.web_search import WebSearchQuery, WebSearchResult, WebSnippet

_INTENT_REASONS = frozenset(
    {
        "explicit_public_search",
        "current_external_info",
        "local_scope",
        "no_search_intent",
        "ambiguous",
    }
)


def result_from_envelope(
    envelope: Mapping[str, Any],
    *,
    query: WebSearchQuery,
    deployment: str,
) -> WebSearchResult:
    output = envelope.get("output")
    if not isinstance(output, list):
        raise RuntimeError("Azure web search response has no output items")
    if not any(
        isinstance(item, Mapping) and item.get("type") == "web_search_call" for item in output
    ):
        raise RuntimeError("Azure model did not perform a web search call")

    answer = response_text(envelope)
    annotations = _url_annotations(output)
    snippets: list[WebSnippet] = []
    seen_urls: set[str] = set()
    fetched_at = datetime.now(tz=UTC)
    for annotation in annotations:
        url = annotation.get("url")
        if not isinstance(url, str) or url in seen_urls:
            continue
        host = _allowed_host(url, query.allowed_domains)
        if host is None:
            continue
        title = annotation.get("title")
        safe_title = title.strip() if isinstance(title, str) and title.strip() else host
        text = _citation_sentence(answer, annotation) or safe_title
        digest = hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()
        snippets.append(
            WebSnippet(
                url=url,
                domain=host,
                title=safe_title,
                text=text,
                content_hash=f"sha256:{digest}",
                fetched_at=fetched_at,
            )
        )
        seen_urls.add(url)
        if len(snippets) >= query.max_results:
            break
    reasons: tuple[str, ...] = ("provider:azure_responses", f"deployment:{deployment}")
    if not snippets:
        reasons = (*reasons, "no_allowlisted_citations")
    return WebSearchResult(query=query, snippets=tuple(snippets), reasons=reasons)


def response_text(envelope: Mapping[str, Any]) -> str:
    direct = envelope.get("output_text")
    if isinstance(direct, str):
        return direct
    output = envelope.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks)


def intent_from_envelope(envelope: Mapping[str, Any]) -> dict[str, object]:
    """Parse one strict structured search-intent response."""

    try:
        raw = json.loads(response_text(envelope))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Azure search intent returned invalid JSON") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"route", "confidence", "reason", "query"}:
        raise RuntimeError("Azure search intent returned an invalid object")
    route = raw.get("route")
    confidence = raw.get("confidence")
    reason = raw.get("reason")
    query = raw.get("query")
    if route not in {"web", "local", "none"}:
        raise RuntimeError("Azure search intent returned an invalid route")
    if (
        not isinstance(confidence, int | float)
        or isinstance(confidence, bool)
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise RuntimeError("Azure search intent returned invalid confidence")
    if reason not in _INTENT_REASONS:
        raise RuntimeError("Azure search intent returned an invalid reason")
    if (
        not isinstance(query, str)
        or len(query) > 1000
        or (route == "web" and not query.strip())
        or (route != "web" and query)
    ):
        raise RuntimeError("Azure search intent returned an invalid query")
    return {
        "route": route,
        "confidence": float(confidence),
        "reason": reason,
        "query": query.strip(),
    }


def _url_annotations(output: list[Any]) -> list[Mapping[str, Any]]:
    annotations: list[Mapping[str, Any]] = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            raw = part.get("annotations")
            if not isinstance(raw, list):
                continue
            annotations.extend(
                annotation
                for annotation in raw
                if isinstance(annotation, Mapping) and annotation.get("type") == "url_citation"
            )
    return annotations


def _allowed_host(url: str, allowed_domains: tuple[str, ...]) -> str | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {domain.lower().rstrip(".") for domain in allowed_domains}
    return host if host in allowed else None


def _citation_sentence(text: str, annotation: Mapping[str, Any]) -> str:
    start = annotation.get("start_index")
    end = annotation.get("end_index")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
        return ""
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    left = 0 if left < 0 else left + 2
    if 0 < end <= len(text) and text[end - 1] in ".?!":
        right = end
    else:
        right_candidates = [
            index for marker in (". ", "\n") if (index := text.find(marker, end)) >= 0
        ]
        right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()[:2_000]


__all__ = ["intent_from_envelope", "response_text", "result_from_envelope"]
