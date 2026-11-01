"""Operator Console public web evidence classifier, resolver, and Azure search seam."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

_UUID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:bearer\s+[a-z0-9._~+/=-]{8,}|api[_-]?key\s*[:=]\s*\S+|client[_-]?secret\s*[:=]\s*\S+)"
)
_QUERY_BOUND_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9 .+-]{2,119}$")
_WORD_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+(?:[.+][a-z0-9]+)*|[가-힣]+")
_INJECTION_PATTERNS: Final[tuple[str, ...]] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "<|im_start|>",
    "</web_snippet>",
    "system prompt:",
)
_PANTHEON_NAMES: Final[frozenset[str]] = frozenset(
    "Odin Forseti Thor Baldur Heimdall Tyr Mimir Freya Huginn Muninn Bragi Norns Loki Vidar Saga Var".split()  # noqa: E501
)
_KO_TO_EN_MAP: Final[tuple[tuple[str, str], ...]] = (
    ("노드", "node"),
    ("오토스케일러", "autoscaler"),
    ("업그레이드", "upgrade"),
    ("지침을", "guidance"),
    ("지침", "guidance"),
    ("최신", "latest"),
    ("패치", "patch"),
    ("릴리스에서", "release"),
    ("릴리스", "release"),
    ("바뀌었는지", "changes"),
    ("변경사항", "changes"),
)
_EN_STOPWORDS: Final[frozenset[str]] = frozenset(
    "a an and can changed current find for in look managed of on please search the to up web what with you alternatives".split()  # noqa: E501
)
_XML_ESCAPES: Final[tuple[tuple[str, str], ...]] = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)


class WebEvidenceRoute(StrEnum):
    WEB = "web"
    LOCAL = "local"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class DelegationAttribution:
    primary: str
    contributors: tuple[str, ...] = ()
    handoff_target: str | None = None
    handoff_reason: str | None = None
    trace_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.primary or len(self.primary) > 64 or self.primary not in _PANTHEON_NAMES:
            raise ValueError("primary attribution MUST be a Pantheon name <= 64 chars")
        if len(self.contributors) > 8 or any(
            not c or len(c) > 64 or c not in _PANTHEON_NAMES for c in self.contributors
        ):
            raise ValueError("contributors MUST contain at most 8 Pantheon names <= 64 chars")
        if self.handoff_target and (
            len(self.handoff_target) > 64 or self.handoff_target not in _PANTHEON_NAMES
        ):
            raise ValueError("handoff_target MUST be a Pantheon name <= 64 chars")
        if (self.handoff_reason and len(self.handoff_reason) > 128) or (
            self.trace_ref and len(self.trace_ref) > 256
        ):
            raise ValueError("handoff_reason or trace_ref exceeds length bound")


@dataclass(frozen=True, slots=True)
class WebTurnContext:
    raw_text: str
    locale: str = "en"
    has_screen_projection: bool = False
    selected_incident_correlation: str | None = None
    has_local_tool_evidence: bool = False
    has_agent_evidence: bool = False
    web_search_enabled: bool = True
    allowed_domains: tuple[str, ...] = ("learn.microsoft.com", "kubernetes.io")
    comparison_subject: str | None = None
    requested_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticWebProposal:
    route: str
    confidence: float
    reason_code: str
    normalized_query: str | None = None
    alternative_discovery: bool = False
    comparison_subject: str | None = None
    capabilities: tuple[str, ...] = ()
    classifier_deployment: str = "gpt-4o-mini-classifier"


@dataclass(frozen=True, slots=True)
class WebEligibilityDecision:
    route: WebEvidenceRoute
    expects_provider_call: bool
    normalized_query: str | None
    alternative_discovery: bool
    min_distinct_products: int | None
    denial_reason: str | None
    reason_code: str
    route_source: str
    comparison_subject: str | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorWebSearchQuery:
    text: str
    allowed_domains: tuple[str, ...]
    max_results: int = 5
    search_context_size: Literal["low", "medium"] = "low"
    alternative_discovery: bool = False
    min_distinct_products: int | None = None
    budget_ms: int = 5_000

    def __post_init__(self) -> None:
        if not _QUERY_BOUND_PATTERN.fullmatch(self.text):
            raise ValueError("OperatorWebSearchQuery.text MUST be bounded lowercase ASCII")
        if not self.allowed_domains or not 1 <= self.max_results <= 20 or self.budget_ms < 1:
            raise ValueError("OperatorWebSearchQuery bounds are invalid")


@dataclass(frozen=True, slots=True)
class OperatorWebSnippet:
    url: str
    domain: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime
    product_id: str | None = None
    authority: Literal["none"] = "none"
    trusted: Literal[False] = False


_FORBIDDEN_CITATION_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1", "169.254.169.254"}
)


def _is_forbidden_ssrf_host(host: str) -> bool:
    normalized = host.strip().lower().rstrip(".")
    if (
        not normalized
        or normalized in _FORBIDDEN_CITATION_HOSTS
        or normalized.endswith((".localhost", ".local"))
    ):
        return True
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_private
        or addr.is_reserved
        or addr.is_multicast
    )


def compute_citation_digest(citations: Sequence[OperatorWebCitation]) -> str:
    """Compute a deterministic `sha256:<64 hex>` digest over resolved citations."""
    payload = [
        {
            "authority": c.authority,
            "domain": c.domain,
            "source_hash": c.source_hash,
            "title": c.title,
            "url": c.url,
        }
        for c in citations
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class OperatorWebCitation:
    url: str
    domain: str
    title: str
    source_hash: str
    authority: Literal["none"] = "none"

    def __post_init__(self) -> None:
        if not is_valid_https_citation_url(self.url):
            raise ValueError(
                "OperatorWebCitation.url MUST use https:// with no credentials or SSRF host"
            )

    @property
    def citation_digest(self) -> str:
        return compute_citation_digest((self,))


def is_valid_https_citation_url(url: str) -> bool:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme.lower() == "https"
        and bool(host)
        and not _is_forbidden_ssrf_host(host)
        and parsed.username is None
        and parsed.password is None
    )


@dataclass(frozen=True, slots=True)
class OperatorWebSearchResponse:
    query: OperatorWebSearchQuery
    snippets: tuple[OperatorWebSnippet, ...] = ()
    declared_source_count: int = 0
    provider_ref: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComparisonRendering:
    status: Literal["complete", "partial", "unavailable"]
    partial: bool
    authority: Literal["none"]
    requested_capabilities: tuple[str, ...]
    retained_products: tuple[str, ...]
    criteria_matrix: Mapping[str, Mapping[str, Literal["cited", "unknown"]]]
    summary_text: str
    citations: tuple[OperatorWebCitation, ...]
    dropped_candidates: tuple[tuple[str, str], ...] = ()

    @property
    def citation_digest(self) -> str:
        return compute_citation_digest(self.citations)


@dataclass(frozen=True, slots=True)
class ResolvedWebEvidence:
    decision: WebEligibilityDecision
    provider_called: bool
    wrapped_snippets: tuple[str, ...] = ()
    citations: tuple[OperatorWebCitation, ...] = ()
    dropped_snippets: tuple[tuple[str, str], ...] = ()
    comparison: ComparisonRendering | None = None
    authority: Literal["none"] = "none"
    attention_state: bool = False
    retained_source_count: int = 0
    declared_source_count: int = 0
    citation_digest: str = ""

    def __post_init__(self) -> None:
        expected = compute_citation_digest(self.citations)
        if not self.citation_digest:
            object.__setattr__(self, "citation_digest", expected)
        elif self.citation_digest != expected:
            raise ValueError("ResolvedWebEvidence.citation_digest mismatch")


@runtime_checkable
class OperatorWebSearchProvider(Protocol):
    async def search(self, query: OperatorWebSearchQuery) -> OperatorWebSearchResponse: ...


class NoOpOperatorWebSearchProvider(OperatorWebSearchProvider):
    async def search(self, query: OperatorWebSearchQuery) -> OperatorWebSearchResponse:
        return OperatorWebSearchResponse(query=query, reasons=("no_op_provider",))


def is_allowed_web_host(host: str, allowed_domains: tuple[str, ...]) -> bool:
    normalized = host.lower().rstrip(".")
    if _is_forbidden_ssrf_host(normalized):
        return False
    allowlist = {domain.lower().rstrip(".") for domain in allowed_domains if domain.strip()}
    return any(normalized == d or normalized.endswith(f".{d}") for d in allowlist)


def sanitize_operator_snippet(
    snippet: OperatorWebSnippet, *, allowed_domains: tuple[str, ...], max_body_chars: int = 4_000
) -> tuple[str | None, str | None]:
    if not allowed_domains:
        return None, "empty_allowlist"
    parsed = urlsplit(snippet.url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if not is_valid_https_citation_url(snippet.url) or not host:
        return None, "invalid_url"
    if not is_allowed_web_host(host, allowed_domains):
        return None, "off_allowlist"
    if snippet.domain.lower().rstrip(".") != host:
        return None, "domain_url_mismatch"
    if any(pattern in snippet.text.casefold() for pattern in _INJECTION_PATTERNS):
        return None, "injection_detected"
    if not snippet.content_hash or not re.fullmatch(
        r"^[A-Za-z0-9_.:-]{4,128}$", snippet.content_hash
    ):
        return None, "invalid_content_hash"
    escaped = snippet.text[:max_body_chars]
    safe_url = snippet.url
    for src, dst in _XML_ESCAPES:
        escaped = escaped.replace(src, dst)
        safe_url = safe_url.replace(src, dst)
    return (
        f'<web_snippet trusted="false" authority="none" url="{safe_url}" '
        f'domain="{host}" content_hash="{snippet.content_hash}">{escaped}</web_snippet>',
        None,
    )


def derive_normalized_web_query(
    raw_text: str, *, comparison_subject: str | None = None, capabilities: Sequence[str] = ()
) -> str | None:
    if capabilities:
        subject_words = set(_WORD_SPLIT_PATTERN.findall((comparison_subject or "").casefold()))
        cap_words = [
            t
            for item in capabilities
            for t in _WORD_SPLIT_PATTERN.findall(item.casefold())
            if t not in subject_words and t not in _EN_STOPWORDS
        ]
        rebuilt = " ".join(cap_words)[:120].strip()
        if _QUERY_BOUND_PATTERN.fullmatch(rebuilt):
            return rebuilt
    lowered = raw_text.casefold().replace("-", " ")
    for ko_token, en_token in _KO_TO_EN_MAP:
        lowered = lowered.replace(ko_token, f" {en_token} ")
    words = [
        t for t in _WORD_SPLIT_PATTERN.findall(lowered) if t.isascii() and t not in _EN_STOPWORDS
    ]
    if ("what changed" in lowered or "무엇이" in lowered) and "changes" not in words:
        words.append("changes")
    candidate = " ".join(words)[:120].strip()
    return candidate if _QUERY_BOUND_PATTERN.fullmatch(candidate) else None


class OperatorWebEvidenceClassifier:
    """Deterministic eligibility ordering with bounded semantic fallback."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.75,
        fallback_evaluator: Callable[[WebTurnContext], SemanticWebProposal | None] | None = None,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence MUST be in [0.0, 1.0]")
        self._min_confidence, self._fallback = min_confidence, fallback_evaluator

    def evaluate(self, context: WebTurnContext) -> WebEligibilityDecision:
        raw, folded = context.raw_text, context.raw_text.casefold()
        if _UUID_PATTERN.search(raw) or _SECRET_PATTERN.search(raw):
            return self._decision(
                WebEvidenceRoute.NONE, "sensitive_input", "sensitive-guard", "sensitive_input"
            )
        screen_cues = ("이 화면", "현재 화면", "this screen", "on this screen", "this incident")
        if (
            context.has_screen_projection
            or context.selected_incident_correlation
            or any(t in folded for t in screen_cues)
        ):
            return self._decision(
                WebEvidenceRoute.LOCAL, "current_screen_precedence", "screen-fast-path"
            )
        local_cues = (
            "stopped db",
            "중지된 db",
            "aks에 연결된",
            "subscription scope",
            "query_inventory",
        )
        if context.has_local_tool_evidence or any(t in folded for t in local_cues):
            return self._decision(
                WebEvidenceRoute.LOCAL, "local_inventory_precedence", "local-fast-path"
            )
        if context.has_agent_evidence or any(
            t in folded for t in ("승인 대기 제안", "pending approval proposal", "active approval")
        ):
            return self._decision(WebEvidenceRoute.NONE, "internal_non_web_turn", "t0-fast-path")
        if not context.web_search_enabled or not context.allowed_domains:
            return self._decision(
                WebEvidenceRoute.NONE, "web_search_disabled", "policy-gate", "web_search_disabled"
            )
        if any(t in folded for t in ("find alternatives", "alternatives to", "대안을 찾아")):
            query = derive_normalized_web_query(
                raw,
                comparison_subject=context.comparison_subject,
                capabilities=context.requested_capabilities,
            )
            if query is not None:
                caps = context.requested_capabilities or (
                    "feature flag service",
                    "audit logging",
                    "staged rollout",
                )
                return self._web(
                    query,
                    "t0_alternative_discovery",
                    "t0-fast-path",
                    alt=True,
                    subject=context.comparison_subject,
                    caps=caps,
                )
        web_cues = ("search the web", "look up", "웹에서 검색", "찾아봐", "구글링해줘")
        if any(t in folded for t in web_cues):
            query = derive_normalized_web_query(raw)
            if query is not None:
                return self._web(query, "t0_explicit_or_colloquial_web", "t0-fast-path")
        return self._evaluate_fallback(context)

    def _evaluate_fallback(self, context: WebTurnContext) -> WebEligibilityDecision:
        proposal = self._fallback(context) if self._fallback else None
        if proposal is None or proposal.confidence < self._min_confidence:
            code = "no_web_signal" if self._fallback is None else "classifier_low_confidence"
            return self._decision(WebEvidenceRoute.NONE, code, "t0-fast-path")
        if proposal.route == WebEvidenceRoute.LOCAL:
            return self._decision(
                WebEvidenceRoute.LOCAL,
                proposal.reason_code or "semantic_local",
                proposal.classifier_deployment,
            )
        if proposal.route != WebEvidenceRoute.WEB:
            return self._decision(
                WebEvidenceRoute.NONE,
                proposal.reason_code or "semantic_none",
                proposal.classifier_deployment,
            )
        if proposal.alternative_discovery and not (2 <= len(proposal.capabilities) <= 8):
            return self._decision(
                WebEvidenceRoute.NONE, "classifier_capability_bounds", "t0-fast-path"
            )
        query = (
            derive_normalized_web_query(
                context.raw_text,
                comparison_subject=proposal.comparison_subject,
                capabilities=proposal.capabilities,
            )
            if proposal.alternative_discovery
            else proposal.normalized_query
        )
        if (
            not query
            or not _QUERY_BOUND_PATTERN.fullmatch(query)
            or bool(_UUID_PATTERN.search(query) or _SECRET_PATTERN.search(query))
        ):
            return self._decision(WebEvidenceRoute.NONE, "classifier_query_bounds", "t0-fast-path")
        return self._web(
            query,
            proposal.reason_code or "semantic_web",
            proposal.classifier_deployment,
            alt=proposal.alternative_discovery,
            subject=proposal.comparison_subject,
            caps=proposal.capabilities,
        )

    @staticmethod
    def _decision(
        route_val: WebEvidenceRoute, reason: str, source: str, denial: str | None = None
    ) -> WebEligibilityDecision:
        return WebEligibilityDecision(route_val, False, None, False, None, denial, reason, source)

    @staticmethod
    def _web(
        query: str,
        reason: str,
        source: str,
        *,
        alt: bool = False,
        subject: str | None = None,
        caps: tuple[str, ...] = (),
    ) -> WebEligibilityDecision:
        return WebEligibilityDecision(
            WebEvidenceRoute.WEB,
            True,
            query,
            alt,
            3 if alt else None,
            None,
            reason,
            source,
            subject,
            caps,
        )
