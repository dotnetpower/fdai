"""Azure Responses search adapter for Operator Console public web evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from fdai_operator_service.web_evidence import (
    _WORD_SPLIT_PATTERN,
    ComparisonRendering,
    OperatorWebCitation,
    OperatorWebSearchProvider,
    OperatorWebSearchQuery,
    OperatorWebSearchResponse,
    OperatorWebSnippet,
    ResolvedWebEvidence,
    WebEligibilityDecision,
    WebEvidenceRoute,
    WebTurnContext,
    is_allowed_web_host,
    is_valid_https_citation_url,
    sanitize_operator_snippet,
)
from fdai_operator_service.web_evidence import (
    OperatorWebEvidenceClassifier as OperatorWebEvidenceClassifier,
)


def _candidate_exclusion_reason(
    snippet: OperatorWebSnippet,
    *,
    comparison_subject: str | None,
) -> str | None:
    parsed = urlsplit(snippet.url)
    path = (parsed.path or "").lower()
    title_lower = snippet.title.casefold()
    text_lower = snippet.text.casefold()
    if comparison_subject:
        subj = comparison_subject.casefold().strip()
        if subj and (
            subj in (snippet.product_id or "").casefold()
            or subj in title_lower
            or subj in snippet.domain.casefold()
        ):
            return "self_reference"
    if path in {"", "/"}:
        return "generic_homepage"
    if "/blog/" in path or "editorial" in title_lower:
        return "editorial_or_blog"
    if "strategy guide" in title_lower or "conceptual framework" in title_lower:
        return "conceptual_content"
    if path.rstrip("/") in {"/docs", "/documentation", "/index"} or "documentation index" in (
        f"{title_lower} {text_lower}"
    ):
        return "generic_doc_index"
    return None


class OperatorWebEvidenceResolver:
    """Coordinate eligibility, provider suppression, candidate diversity, and partial rendering."""

    def __init__(
        self,
        *,
        classifier: OperatorWebEvidenceClassifier,
        provider: OperatorWebSearchProvider,
    ) -> None:
        self._classifier = classifier
        self._provider = provider

    async def resolve(self, context: WebTurnContext) -> ResolvedWebEvidence:
        decision = self._classifier.evaluate(context)
        if (
            decision.route is not WebEvidenceRoute.WEB
            or not decision.expects_provider_call
            or decision.normalized_query is None
        ):
            return ResolvedWebEvidence(decision=decision, provider_called=False)
        query = OperatorWebSearchQuery(
            text=decision.normalized_query,
            allowed_domains=context.allowed_domains,
            max_results=8 if decision.alternative_discovery else 5,
            search_context_size="medium" if decision.alternative_discovery else "low",
            alternative_discovery=decision.alternative_discovery,
            min_distinct_products=decision.min_distinct_products,
        )
        response = await self._provider.search(query)
        wrapped_list: list[str] = []
        citations: list[OperatorWebCitation] = []
        retained_snippets: list[OperatorWebSnippet] = []
        dropped: list[tuple[str, str]] = []
        seen_identities: set[str] = set()
        for snippet in response.snippets[: query.max_results]:
            wrapped, err = sanitize_operator_snippet(
                snippet, allowed_domains=context.allowed_domains
            )
            if err is not None or wrapped is None:
                dropped.append((snippet.content_hash, err or "sanitize_failed"))
                continue
            if decision.alternative_discovery:
                exclusion = _candidate_exclusion_reason(
                    snippet, comparison_subject=decision.comparison_subject
                )
                if exclusion is not None:
                    dropped.append((snippet.content_hash, exclusion))
                    continue
            identity = (snippet.product_id or snippet.domain).casefold().strip()
            if identity in seen_identities:
                dropped.append((snippet.content_hash, "duplicate_product_identity"))
                continue
            seen_identities.add(identity)
            wrapped_list.append(wrapped)
            retained_snippets.append(snippet)
            citations.append(
                OperatorWebCitation(
                    url=snippet.url,
                    domain=snippet.domain,
                    title=snippet.title,
                    source_hash=snippet.content_hash,
                )
            )
        declared = max(response.declared_source_count, len(response.snippets))
        comparison = (
            self._render_comparison(
                decision=decision,
                snippets=retained_snippets,
                citations=tuple(citations),
                dropped=tuple(dropped),
            )
            if decision.alternative_discovery
            else None
        )
        attention = bool(
            dropped
            or declared > len(retained_snippets)
            or (comparison is not None and comparison.status != "complete")
        )
        return ResolvedWebEvidence(
            decision=decision,
            provider_called=True,
            wrapped_snippets=tuple(wrapped_list),
            citations=tuple(citations),
            dropped_snippets=tuple(dropped),
            comparison=comparison,
            authority="none",
            attention_state=attention,
            retained_source_count=len(retained_snippets),
            declared_source_count=declared,
        )

    @staticmethod
    def _render_comparison(
        *,
        decision: WebEligibilityDecision,
        snippets: list[OperatorWebSnippet],
        citations: tuple[OperatorWebCitation, ...],
        dropped: tuple[tuple[str, str], ...],
    ) -> ComparisonRendering:
        capabilities = decision.capabilities or (
            "feature flag service",
            "audit logging",
            "staged rollout",
        )
        products = tuple(s.product_id or s.domain for s in snippets)
        if len(products) < 2:
            return ComparisonRendering(
                status="unavailable",
                partial=True,
                authority="none",
                requested_capabilities=capabilities,
                retained_products=products,
                criteria_matrix={},
                summary_text=(
                    "Partial evidence: fewer than two distinct product sources were retained; "
                    "comparison is unavailable."
                ),
                citations=citations,
                dropped_candidates=dropped,
            )
        matrix: dict[str, dict[str, Any]] = {}
        for snippet in snippets:
            prod = snippet.product_id or snippet.domain
            body_folded = f"{snippet.title} {snippet.text}".casefold()
            row: dict[str, Any] = {}
            for cap in capabilities:
                cap_tokens = [t for t in _WORD_SPLIT_PATTERN.findall(cap.casefold()) if len(t) > 2]
                row[cap] = (
                    "cited"
                    if cap_tokens and all(tok in body_folded for tok in cap_tokens)
                    else "unknown"
                )
            matrix[prod] = row
        summary = (
            f"Partial capability overlap across {', '.join(products)}; "
            "unsupported criteria are marked unknown and no winner is claimed."
        )
        return ComparisonRendering(
            status="partial",
            partial=True,
            authority="none",
            requested_capabilities=capabilities,
            retained_products=products,
            criteria_matrix=matrix,
            summary_text=summary,
            citations=citations,
            dropped_candidates=dropped,
        )


class AzureOperatorWebSearchError(RuntimeError):
    """Content-free failure from the Operator Azure web-search adapter."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Operator Azure web search failed: {reason}")


@dataclass(frozen=True, slots=True)
class AzureOperatorWebSearchConfig:
    """Server-owned target and domain allowlist bounds for Operator web search."""

    endpoint: str
    deployment: str
    allowed_domains: tuple[str, ...]
    max_results: int = 8
    max_output_tokens: int = 900
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" and host not in {"127.0.0.1", "localhost"}:
            raise ValueError("AzureOperatorWebSearchConfig.endpoint MUST use https")
        if not self.deployment.strip():
            raise ValueError("AzureOperatorWebSearchConfig.deployment MUST be non-empty")
        if not self.allowed_domains or len(self.allowed_domains) > 100:
            raise ValueError("AzureOperatorWebSearchConfig requires 1 to 100 allowed domains")
        normalized = tuple(domain.lower().strip().rstrip(".") for domain in self.allowed_domains)
        if any(not domain or "/" in domain or " " in domain for domain in normalized):
            raise ValueError("AzureOperatorWebSearchConfig allowed_domains MUST be hostnames")
        if len(normalized) != len(set(normalized)):
            raise ValueError("AzureOperatorWebSearchConfig allowed_domains MUST be unique")
        object.__setattr__(self, "allowed_domains", normalized)
        if not 1 <= self.max_results <= 20:
            raise ValueError("AzureOperatorWebSearchConfig.max_results MUST be in [1, 20]")


class AzureOperatorWebSearchAdapter(OperatorWebSearchProvider):
    """Execute one bounded Operator public-web query against Azure Responses."""

    def __init__(
        self,
        *,
        config: AzureOperatorWebSearchConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], Awaitable[str]],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._token_provider = token_provider
        self._now = now or (lambda: datetime.now(UTC))

    async def search(self, query: OperatorWebSearchQuery) -> OperatorWebSearchResponse:
        normalized_query_domains = tuple(
            domain.lower().strip().rstrip(".") for domain in query.allowed_domains
        )
        if normalized_query_domains != self._config.allowed_domains:
            raise AzureOperatorWebSearchError("domain_policy_mismatch")
        if query.max_results > self._config.max_results:
            raise AzureOperatorWebSearchError("result_bound_exceeded")
        token = await self._token_provider()
        payload: dict[str, Any] = {
            "model": self._config.deployment,
            "tools": [
                {
                    "type": "web_search",
                    "search_context_size": query.search_context_size,
                    "filters": {"allowed_domains": list(self._config.allowed_domains)},
                }
            ],
            "tool_choice": "required",
            "include": ["web_search_call.action.sources"],
            "max_output_tokens": self._config.max_output_tokens,
            "input": [{"role": "user", "content": query.text}],
        }
        timeout = max(0.1, min(self._config.timeout_seconds, query.budget_ms / 1_000))
        try:
            response = await self._http.post(
                f"{self._config.endpoint.rstrip('/')}/openai/v1/responses",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise AzureOperatorWebSearchError("provider_unreachable") from exc
        if response.status_code >= 400 or response.is_redirect:
            raise AzureOperatorWebSearchError(f"http_{response.status_code}")
        try:
            envelope = response.json()
        except ValueError as exc:
            raise AzureOperatorWebSearchError("invalid_response") from exc
        if not isinstance(envelope, Mapping):
            raise AzureOperatorWebSearchError("invalid_response")
        return self._parse_envelope(envelope, query=query)

    def _parse_envelope(
        self,
        envelope: Mapping[str, Any],
        *,
        query: OperatorWebSearchQuery,
    ) -> OperatorWebSearchResponse:
        raw_sources = envelope.get("sources", ())
        if not isinstance(raw_sources, list):
            raise AzureOperatorWebSearchError("invalid_sources")
        fetched_at = self._now()
        snippets: list[OperatorWebSnippet] = []
        for item in raw_sources[: query.max_results]:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url", "")).strip()
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if not is_valid_https_citation_url(url) or not host:
                raise AzureOperatorWebSearchError("invalid_source_url")
            if not is_allowed_web_host(host, self._config.allowed_domains):
                raise AzureOperatorWebSearchError("off_allowlist_source")
            text = str(item.get("snippet", item.get("text", ""))).strip()
            title = str(item.get("title", host)).strip() or host
            product_id = item.get("product_id")
            digest = hashlib.sha256(f"{url}\n{title}\n{text}".encode()).hexdigest()
            snippets.append(
                OperatorWebSnippet(
                    url=url,
                    domain=host,
                    title=title,
                    text=text,
                    content_hash=f"sha256:{digest}",
                    fetched_at=fetched_at,
                    product_id=str(product_id) if isinstance(product_id, str) else None,
                )
            )
        declared = int(envelope.get("declared_source_count", len(raw_sources)))
        provider_ref = envelope.get("id")
        return OperatorWebSearchResponse(
            query=query,
            snippets=tuple(snippets),
            declared_source_count=declared,
            provider_ref=str(provider_ref) if isinstance(provider_ref, str) else None,
        )


__all__ = [
    "AzureOperatorWebSearchAdapter",
    "AzureOperatorWebSearchConfig",
    "AzureOperatorWebSearchError",
    "OperatorWebEvidenceClassifier",
    "OperatorWebEvidenceResolver",
]
