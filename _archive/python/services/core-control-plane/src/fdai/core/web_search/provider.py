"""WebSearchProvider seam + deny-by-default no-op (Wave 5 alpha).

Web search is the last-resort tool per
``docs/roadmap/decisioning/prompt-composition.md § Web search policy``. It is
opt-in per fork and never a grounding source: even the most useful
web finding does not satisfy the current event's ``cited_rule_ids``
requirement.

Upstream ships:

- :class:`WebSearchProvider` - the ``async`` Protocol every concrete
  adapter implements.
- :class:`NoOpWebSearchProvider` - the shipped default. Returns
  zero snippets on every query and records the reason on
  :class:`~fdai.core.web_search.types.WebSearchResult` so an
  operator sees exactly why the search degraded. A fork wires a
  real provider (Bing, SerpAPI, curated crawler, ...) at the
  composition root; the Protocol stays identical.

The provider layer intentionally does no injection sanitization -
that lives in :mod:`~fdai.core.web_search.sanitizer` so the
same defense applies whether the snippet came from a live provider,
a replay cache, or a hand-authored test fixture.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdai.core.web_search.types import WebSearchQuery, WebSearchResult

_NOOP_REASON: str = "no_op_provider"
"""Reason recorded on the deny-by-default result so an operator can
grep the audit log to distinguish "no provider wired" from "provider
returned zero snippets"."""


@runtime_checkable
class WebSearchProvider(Protocol):
    """Async surface every web-search adapter implements.

    A single method keeps the contract minimal - adapters that need
    to plumb API keys / rate limiters accept them via their own
    constructor at the composition root. The Protocol MUST NOT expose
    those secrets in its signatures.
    """

    async def search(self, query: WebSearchQuery) -> WebSearchResult: ...


class NoOpWebSearchProvider(WebSearchProvider):
    """Deny-by-default fake.

    Returns :attr:`WebSearchResult(snippets=())` for every query and
    records ``no_op_provider`` on the reasons tuple. Fork composition
    roots swap this out for a real adapter; until then the T2 debate
    behaves exactly as if no web search was configured - which is the
    documented default.
    """

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        return WebSearchResult(query=query, reasons=(_NOOP_REASON,))


__all__ = [
    "NoOpWebSearchProvider",
    "WebSearchProvider",
]
