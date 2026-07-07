"""Web search seam for the T2 tier (Wave 5 alpha).

Web search is the last-resort tool per the web-search policy in
``docs/roadmap/prompt-composition.md``. Upstream ships:

- typed primitives (:class:`WebSearchQuery`, :class:`WebSnippet`,
  :class:`WebSearchResult`);
- the async :class:`WebSearchProvider` :class:`typing.Protocol` every
  concrete adapter implements;
- :class:`NoOpWebSearchProvider` - the deny-by-default fake so a
  fork that has not activated web search sees no snippets at all;
- :func:`wrap_web_snippet` + :func:`validate_snippet_domain` +
  :func:`detect_snippet_injection_markers` - the sanitization
  defenses that every snippet MUST pass before it can reach a model
  turn.

A fork opts in to web search by binding a real
:class:`WebSearchProvider` at the composition root and populating
:attr:`WebSearchQuery.allowed_domains` with a curated primary-source
allowlist. The upstream default keeps web search off entirely.
"""

from __future__ import annotations

from aiopspilot.core.web_search.provider import (
    NoOpWebSearchProvider,
    WebSearchProvider,
)
from aiopspilot.core.web_search.sanitizer import (
    InjectionMarkerError,
    WebSnippetPolicyError,
    detect_snippet_injection_markers,
    validate_snippet_domain,
    wrap_web_snippet,
)
from aiopspilot.core.web_search.types import (
    WebSearchQuery,
    WebSearchResult,
    WebSnippet,
)

__all__ = [
    "InjectionMarkerError",
    "NoOpWebSearchProvider",
    "WebSearchProvider",
    "WebSearchQuery",
    "WebSearchResult",
    "WebSnippet",
    "WebSnippetPolicyError",
    "detect_snippet_injection_markers",
    "validate_snippet_domain",
    "wrap_web_snippet",
]
