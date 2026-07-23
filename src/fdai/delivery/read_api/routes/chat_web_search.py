"""Controlled public-web evidence for Command Deck conversations."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, Protocol

import httpx

from fdai.core.web_search import (
    WebSearchPolicyConfig,
    WebSearchQuery,
    WebSearchResult,
    WebSearchSignals,
    decide_web_search,
    sanitize_web_result,
)
from fdai.delivery.azure.web_search import (
    AzureResponsesWebSearchCandidate,
    AzureResponsesWebSearchConfig,
    LatencyRoutedWebSearchProvider,
    WebSearchModelCandidate,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOG = logging.getLogger(__name__)

_ENABLED_ENV: Final[str] = "FDAI_WEB_SEARCH_ENABLED"
_DOMAINS_ENV: Final[str] = "FDAI_WEB_SEARCH_ALLOWED_DOMAINS"
_MAX_RESULTS_ENV: Final[str] = "FDAI_WEB_SEARCH_MAX_RESULTS"
_BUDGET_MS_ENV: Final[str] = "FDAI_WEB_SEARCH_BUDGET_MS"
_PROBE_INTERVAL_ENV: Final[str] = "FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS"
_RESOLVED_MODELS_ENV: Final[str] = "LLM_RESOLVED_MODELS_PATH"

_EXPLICIT_WEB_SEARCH = re.compile(
    r"\b(?:search|browse)\s+(?:the\s+)?(?:web|internet|online)\b"
    r"|\b(?:web|internet)\s+search\b"
    "|(?:\uc778\ud130\ub137|\uc6f9).{0,80}(?:\uac80\uc0c9|\ucc3e\uc544|\uc870\uc0ac)"
    "|(?:\uac80\uc0c9|\ucc3e\uc544|\uc870\uc0ac).{0,80}(?:\uc778\ud130\ub137|\uc6f9)",
    re.IGNORECASE,
)
_WEB_CONTEXT = re.compile(
    r"\b(?:web|internet|online)\b|\uc778\ud130\ub137|\uc6f9|\uc628\ub77c\uc778",
    re.IGNORECASE,
)
_EXPLICIT_SEARCH_REQUEST = re.compile(
    r"\b(?:search|find|look\s+up|research|discover|google|browse)\b"
    "|(?:\uac80\uc0c9|\uc870\uc0ac|\uad6c\uae00\ub9c1)\\s*(?:\ud574|\ud574\uc11c|\ud574\uc918|\ud574\ubd10|\ud574\uc904\ub798|\ud574\uc8fc\uc138\uc694|\ubd80\ud0c1)"
    "|\ucc3e\uc544\\s*(?:\ubd10|\uc918|\uc904\ub798|\uc8fc\uc138\uc694)"
    "|\uc54c\uc544\\s*(?:\ubd10|\uc918|\uc904\ub798|\uc8fc\uc138\uc694)",
    re.IGNORECASE,
)
_PUBLIC_DISCOVERY_SUBJECT = re.compile(
    r"\b(?:service|product|tool|solution|platform|alternative|competitor)s?\b"
    "|\uc11c\ube44\uc2a4|\uc81c\ud488|\ub3c4\uad6c|\uc194\ub8e8\uc158|\ud50c\ub7ab\ud3fc|\ub300\uc548|\uacbd\uc7c1",
    re.IGNORECASE,
)
_LOCAL_SEARCH_SCOPE = re.compile(
    r"\b(?:this|current)\s+(?:screen|page|table|list|view)\b"
    r"|\b(?:audit|activity)\s+logs?\b"
    r"|\b(?:in|from|within)\s+(?:the\s+)?(?:inventory|catalog|database|db)\b"
    "|(?:\uc774|\ud604\uc7ac)\\s*(?:\ud654\uba74|\ud398\uc774\uc9c0|\ud45c|\ubaa9\ub85d|\ubdf0)"
    "|(?:\uac10\uc0ac|\ud65c\ub3d9)\\s*\ub85c\uadf8"
    "|(?:\uc778\ubca4\ud1a0\ub9ac|\uce74\ud0c8\ub85c\uadf8|\ub370\uc774\ud130\ubca0\uc774\uc2a4|\ub514\ube44)(?:\uc5d0\uc11c|\\s*\uc548\uc5d0\uc11c|\\s*\ub0b4\uc5d0\uc11c)",
    re.IGNORECASE,
)
_FRESHNESS = re.compile(
    r"\b(?:latest|newest|today|recent|currently|now|trending|current\s+(?:release|version)|recently\s+released"
    r"|as\s+of\s+today|release\s+notes?)\b"
    "|\ucd5c\uc2e0|\uc624\ub298|\uc694\uc998|\ucd5c\uadfc|\uc9c0\uae08|\ud604\uc7ac\\s*\ubc84\uc804|\ucd5c\uadfc\\s*\ubc1c\ud45c"
    "|\ub9b4\ub9ac\uc2a4\\s*\ub178\ud2b8",
    re.IGNORECASE,
)
_PUBLIC_SUBJECT = re.compile(
    r"\b(?:azure|microsoft|foundry|openai|python|kubernetes|aks|postgres(?:ql)?"
    r"|cve|nvd|rfc|sdk|api|documentation|docs?|release|version|package|library)\b"
    "|\uacf5\uc2dd\\s*\ubb38\uc11c|\ubcf4\uc548\\s*\uacf5\uc9c0"
    "|\ucde8\uc57d\uc810|\ubc84\uc804|\ub9b4\ub9ac\uc2a4",
    re.IGNORECASE,
)
_SENSITIVE_QUERY = re.compile(
    r"/subscriptions/|/resourceGroups/"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    r"|\b(?:10\.|127\.|169\.254\.|192\.168\.)\d{1,3}(?:\.\d{1,3}){2}\b",
    re.IGNORECASE,
)
_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)


class _SearchIntentDecision(NamedTuple):
    route: Literal["web", "local", "none"]
    novelty_score: float
    reason: str


class ChatWebSearchProvider(Protocol):
    async def search(self, query: WebSearchQuery) -> WebSearchResult: ...


@dataclass(frozen=True, slots=True)
class ChatWebSearchConfig:
    """Bounded policy values for one conversational web-search call."""

    allowed_domains: tuple[str, ...]
    max_results: int = 3
    budget_ms: int = 15_000
    probe_interval_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.allowed_domains:
            raise ValueError("web search requires at least one allowed domain")
        if len(self.allowed_domains) > 100:
            raise ValueError("web search supports at most 100 allowed domains")
        if not 1 <= self.max_results <= 10:
            raise ValueError("web search max_results MUST be in [1, 10]")
        if self.budget_ms < 1:
            raise ValueError("web search budget_ms MUST be >= 1")
        if self.probe_interval_seconds < 30:
            raise ValueError("web search probe interval MUST be >= 30 seconds")


class ChatWebSearchResolver:
    """Decide, fetch, sanitize, and expose server-owned public-web evidence."""

    def __init__(
        self,
        *,
        provider: ChatWebSearchProvider,
        config: ChatWebSearchConfig,
    ) -> None:
        self._provider = provider
        self._config = config
        self._policy = WebSearchPolicyConfig(enabled=True)

    def update_settings(
        self,
        *,
        enabled: bool,
        allowed_domains: tuple[str, ...],
    ) -> None:
        """Atomically replace deployment-wide search policy values."""
        config = ChatWebSearchConfig(
            allowed_domains=allowed_domains,
            max_results=self._config.max_results,
            budget_ms=self._config.budget_ms,
            probe_interval_seconds=self._config.probe_interval_seconds,
        )
        self._config = config
        self._policy = WebSearchPolicyConfig(enabled=enabled)

    @property
    def probe_interval_seconds(self) -> int:
        return self._config.probe_interval_seconds

    async def benchmark(self, *, rounds: int | None = None) -> str | None:
        benchmark = getattr(self._provider, "benchmark", None)
        if benchmark is None:
            return None
        return str(await benchmark(rounds=rounds))

    def descriptor(self) -> dict[str, Any]:
        stats_fn = getattr(self._provider, "stats", None)
        pick_fn = getattr(self._provider, "current_pick_name", None)
        candidates = stats_fn() if stats_fn is not None else []
        chose = pick_fn() if pick_fn is not None else None
        return {
            "available": True,
            "enabled": self._policy.enabled,
            "mode": "azure-responses-web-search",
            "allowed_domains": list(self._config.allowed_domains),
            "router": {
                "chose": chose,
                "candidates": candidates,
            },
        }

    async def resolve(
        self,
        prompt: str,
        view_context: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        search_intent = _classify_search_intent(prompt)
        if search_intent.route != "web":
            return None
        if _SENSITIVE_QUERY.search(prompt):
            _LOG.warning("chat.web_search_blocked_sensitive_query")
            return {
                "status": "skipped",
                "reason": "query_not_public_safe",
                "sources": [],
            }

        signals = WebSearchSignals(
            is_reasoning_tier=True,
            novelty_score=search_intent.novelty_score,
            grounding_gap=True,
            allowlist_has_web_search=True,
            provider_available=True,
            query_budget_remaining=1,
            cost_budget_remaining_usd=0.01,
        )
        decision = decide_web_search(self._policy, signals)
        if not decision.should_search:
            return None

        query = WebSearchQuery(
            text=prompt[:1000],
            allowed_domains=self._config.allowed_domains,
            max_results=self._config.max_results,
            budget_ms=self._config.budget_ms,
            metadata={"surface": "operator-console", "tier": "chat-t2"},
        )
        try:
            result = await self._provider.search(query)
        except Exception as exc:  # noqa: BLE001 - web evidence fails closed
            _LOG.warning(
                "chat.web_search_failed",
                extra={"error_type": type(exc).__name__},
            )
            return {
                "status": "unavailable",
                "reason": "provider_error",
                "sources": [],
            }

        sanitized = sanitize_web_result(result)
        dropped_hashes = {content_hash for content_hash, _ in sanitized.dropped}
        sources = [
            {
                "title": snippet.title,
                "url": snippet.url,
                "domain": snippet.domain,
                "content_hash": snippet.content_hash,
                "fetched_at": snippet.fetched_at.isoformat(),
            }
            for snippet in result.snippets
            if snippet.content_hash not in dropped_hashes
        ]
        return {
            "status": "matched" if sanitized.wrapped else "unavailable",
            "reason": decision.reason,
            "snippets": list(sanitized.wrapped),
            "sources": sources,
            "dropped": [
                {"content_hash": content_hash, "reason": reason}
                for content_hash, reason in sanitized.dropped
            ],
            "provider_reasons": list(result.reasons),
            "router": self.descriptor()["router"],
        }


def chat_web_search_from_env(
    env: Mapping[str, str] | None = None,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ChatWebSearchResolver | None:
    """Build the opt-in Azure Responses web-search resolver from config."""

    source = env if env is not None else os.environ
    if not _parse_enabled(source.get(_ENABLED_ENV)):
        return None
    domains = _parse_domains(source.get(_DOMAINS_ENV, ""))
    config = ChatWebSearchConfig(
        allowed_domains=domains,
        max_results=_parse_int(source, _MAX_RESULTS_ENV, 3),
        budget_ms=_parse_int(source, _BUDGET_MS_ENV, 15_000),
        probe_interval_seconds=_parse_int(source, _PROBE_INTERVAL_ENV, 300),
    )
    model_data = _load_resolved_models(source)
    raw_candidates = model_data.get("narrator_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        narrator = model_data.get("narrator")
        raw_candidates = [narrator] if isinstance(narrator, Mapping) else []

    candidates: list[tuple[str, WebSearchModelCandidate]] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        endpoint = raw.get("endpoint")
        deployment = raw.get("deployment")
        if not isinstance(endpoint, str) or not isinstance(deployment, str):
            continue
        if deployment in seen:
            continue
        seen.add(deployment)
        candidates.append(
            (
                deployment,
                AzureResponsesWebSearchCandidate(
                    config=AzureResponsesWebSearchConfig(
                        endpoint=endpoint,
                        deployment=deployment,
                    ),
                    identity=identity,
                    http_client=http_client,
                ),
            )
        )
    if not candidates:
        raise ValueError(
            "web search is enabled but resolved-models.json has no narrator candidates"
        )
    return ChatWebSearchResolver(
        provider=LatencyRoutedWebSearchProvider(candidates=candidates),
        config=config,
    )


def _classify_search_intent(prompt: str) -> _SearchIntentDecision:
    if _EXPLICIT_WEB_SEARCH.search(prompt):
        return _SearchIntentDecision("web", 1.0, "explicit_web_search")
    search_requested = _EXPLICIT_SEARCH_REQUEST.search(prompt) is not None
    if _WEB_CONTEXT.search(prompt) and (
        search_requested or _PUBLIC_DISCOVERY_SUBJECT.search(prompt)
    ):
        return _SearchIntentDecision("web", 1.0, "explicit_web_context")
    if search_requested and _LOCAL_SEARCH_SCOPE.search(prompt):
        return _SearchIntentDecision("local", 0.0, "explicit_local_scope")
    if search_requested:
        return _SearchIntentDecision("web", 1.0, "explicit_search_request")
    if _FRESHNESS.search(prompt) and (
        _PUBLIC_SUBJECT.search(prompt) or _PUBLIC_DISCOVERY_SUBJECT.search(prompt)
    ):
        return _SearchIntentDecision("web", 0.8, "fresh_public_subject")
    return _SearchIntentDecision("none", 0.0, "no_search_intent")


def _parse_enabled(raw: str | None) -> bool:
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{_ENABLED_ENV} MUST be a boolean")


def _parse_domains(raw: str) -> tuple[str, ...]:
    domains = tuple(
        dict.fromkeys(part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip())
    )
    if not domains:
        raise ValueError(f"{_DOMAINS_ENV} MUST contain at least one domain")
    invalid = [domain for domain in domains if not _DOMAIN.fullmatch(domain)]
    if invalid:
        raise ValueError(f"{_DOMAINS_ENV} contains an invalid domain")
    return domains


def _parse_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc


def _load_resolved_models(source: Mapping[str, str]) -> Mapping[str, Any]:
    path = _find_resolved_models(source)
    if path is None:
        raise ValueError("web search is enabled but LLM_RESOLVED_MODELS_PATH could not be resolved")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("resolved-models.json is not readable JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("resolved-models.json MUST contain an object")
    return payload


def _find_resolved_models(source: Mapping[str, str]) -> Path | None:
    explicit = source.get(_RESOLVED_MODELS_ENV)
    if explicit is not None:
        path = Path(explicit)
        return path if path.is_file() else None
    for start in (Path.cwd(), Path(__file__).resolve()):
        for directory in (start, *start.parents):
            candidate = directory / "resolved-models.json"
            if candidate.is_file():
                return candidate
    return None


__all__ = ["ChatWebSearchConfig", "ChatWebSearchResolver", "chat_web_search_from_env"]
