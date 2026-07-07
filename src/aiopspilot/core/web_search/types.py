"""Type primitives for the T2 web search seam (Wave 5 alpha).

The retrieved web snippets are **untrusted data**, not instructions.
Every field here is a plain frozen dataclass so a caller can hand
snippets across the composer / audit boundary without accidentally
mutating them.

Design references:
- ``docs/roadmap/prompt-composition.md § Web search policy``
- ``docs/roadmap/prompt-composition.md § Role x Layer matrix``
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class WebSearchQuery:
    """Envelope handed to :meth:`WebSearchProvider.search`.

    ``allowed_domains`` is the caller-supplied allowlist for the
    fetch - primary sources only (vendor docs, RFCs, NVD, CVE
    registries per the web-search policy). A concrete provider MUST
    refuse to return snippets from any domain outside this tuple;
    the no-op fake enforces the invariant by never returning
    snippets at all.

    ``max_results`` caps the number of snippets the provider may
    return; it is a cost / attack-surface bound the provider MUST
    respect, not a hint.

    ``budget_ms`` is a soft deadline; providers SHOULD abort in-
    flight fetches on overshoot and return whatever snippets they
    already have (up to ``max_results``).
    """

    text: str
    allowed_domains: tuple[str, ...] = ()
    max_results: int = 3
    budget_ms: int = 5_000
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("WebSearchQuery.text MUST be non-empty")
        if self.max_results < 1:
            raise ValueError("WebSearchQuery.max_results MUST be >= 1")
        if self.budget_ms < 1:
            raise ValueError("WebSearchQuery.budget_ms MUST be >= 1")


@dataclass(frozen=True, slots=True)
class WebSnippet:
    """One retrieved snippet.

    ``content_hash`` is a stable identifier for the snippet body -
    audit entries reference this hash so a replay reads the stored
    snapshot instead of re-fetching. Providers MUST populate it with
    a deterministic hash of the raw content (typically a hex-encoded
    SHA-256).

    ``fetched_at`` is the wall-clock time the provider retrieved the
    content; combined with ``content_hash`` it forms the replay-key
    documented in the web search policy.

    ``domain`` MUST be one of the ``allowed_domains`` on the
    originating :class:`WebSearchQuery`; a provider that returns a
    snippet with an off-allowlist domain is a defect the sanitizer /
    caller MUST reject.
    """

    url: str
    domain: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("WebSnippet.url MUST be non-empty")
        if not self.domain:
            raise ValueError("WebSnippet.domain MUST be non-empty")
        if not self.content_hash:
            raise ValueError("WebSnippet.content_hash MUST be non-empty")


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    """The return shape of :meth:`WebSearchProvider.search`.

    ``snippets`` is empty when the query returned nothing OR when the
    provider is the deny-by-default no-op (Wave 5 alpha default -
    forks activate a real provider explicitly).

    ``reasons`` records why the search may have degraded (allowlist
    empty, budget exhausted, no snippets found, provider unavailable);
    the caller threads these into the audit log so an operator can
    inspect why a T2 event did not consult the web.
    """

    query: WebSearchQuery
    snippets: tuple[WebSnippet, ...] = ()
    reasons: tuple[str, ...] = ()


__all__ = [
    "WebSearchQuery",
    "WebSearchResult",
    "WebSnippet",
]
