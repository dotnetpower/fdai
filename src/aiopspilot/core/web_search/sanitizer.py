"""Sanitize + wrap web snippets for prompt injection (Wave 5 alpha).

Web-retrieved text is **data**, not instructions. Three defenses
layer here:

1. :func:`detect_snippet_injection_markers` - reuses the same
   marker list :mod:`aiopspilot.core.operator_memory.sanitizer`
   uses so any pattern already blocked from operator memory is
   blocked from web snippets too. A hit fails closed so the caller
   quarantines the snippet before it reaches a model turn.
2. :func:`validate_snippet_domain` - refuses any snippet whose
   ``domain`` is not on the query's ``allowed_domains`` tuple. This
   defends against a provider bug (or an attacker who spoofed the
   result) that would smuggle an off-allowlist source into the T2
   context.
3. :func:`wrap_web_snippet` - renders the (sanitized) body inside a
   ``<web_snippet trusted="false" ...>...</web_snippet>`` envelope
   matching the ``trusted="false"`` invariant the T2 base prompt
   enforces on tool output.

The functions are pure so any layer (the composer inject path, a
future recognition probe, a fork's alternate rendering) reuses the
same defense without shared mutable state.
"""

from __future__ import annotations

from typing import Final

from aiopspilot.core.operator_memory.sanitizer import (
    InjectionMarkerError,
    detect_injection_markers,
)
from aiopspilot.core.web_search.types import WebSnippet

_XML_ESCAPES: Final[tuple[tuple[str, str], ...]] = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)


class WebSnippetPolicyError(ValueError):
    """Raised when a snippet violates a sanitization policy.

    Structured with a stable ``code`` so a caller can dispatch on
    it for telemetry without pattern-matching on error messages.
    Codes:

    - ``off_allowlist`` - snippet ``domain`` is not on the query's
      allowlist;
    - ``empty_allowlist`` - the query supplied an empty allowlist
      (the caller MUST populate it before shipping snippets into a
      prompt);
    - ``injection_markers_detected`` - the snippet body carries at
      least one injection marker (raised by
      :class:`InjectionMarkerError` under the hood).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code: Final[str] = code
        super().__init__(f"{code}: {message}")


def detect_snippet_injection_markers(text: str) -> tuple[str, ...]:
    """Return every injection marker present in a snippet body.

    Delegates to :func:`detect_injection_markers` so the marker set
    stays synchronized with the operator-memory sanitizer. Empty
    tuple means the snippet is safe by this defense.
    """

    return detect_injection_markers(text)


def validate_snippet_domain(
    *,
    snippet: WebSnippet,
    allowed_domains: tuple[str, ...],
) -> None:
    """Refuse a snippet whose domain is not on the allowlist.

    Empty ``allowed_domains`` is itself a policy failure - the
    caller MUST populate the allowlist BEFORE receiving snippets;
    an empty tuple means the snippet has no legitimate source.
    """

    if not allowed_domains:
        raise WebSnippetPolicyError(
            "empty_allowlist",
            "allowed_domains is empty; a snippet cannot legitimately reach the prompt",
        )
    if snippet.domain not in allowed_domains:
        raise WebSnippetPolicyError(
            "off_allowlist",
            f"snippet domain {snippet.domain!r} is not in the allowlist {allowed_domains!r}",
        )


def wrap_web_snippet(
    *,
    snippet: WebSnippet,
    allowed_domains: tuple[str, ...],
) -> str:
    """Render a snippet inside its ``trusted="false"`` envelope.

    Runs both defenses first (domain allowlist + injection markers)
    and only then wraps the body. XML meta-characters in attribute
    values and body are escaped so a snippet cannot forge the
    closing tag or inject arbitrary attributes.

    Raises:
        WebSnippetPolicyError: domain not on allowlist / allowlist empty.
        InjectionMarkerError: body carries at least one injection marker.
    """

    validate_snippet_domain(snippet=snippet, allowed_domains=allowed_domains)
    markers = detect_snippet_injection_markers(snippet.text)
    if markers:
        raise InjectionMarkerError(markers)
    return (
        '<web_snippet trusted="false" '
        f'url="{_xml_escape(snippet.url)}" '
        f'domain="{_xml_escape(snippet.domain)}" '
        f'content_hash="{_xml_escape(snippet.content_hash)}">'
        f"{_xml_escape(snippet.text)}"
        "</web_snippet>"
    )


def _xml_escape(value: str) -> str:
    escaped = value
    for src, dst in _XML_ESCAPES:
        escaped = escaped.replace(src, dst)
    return escaped


__all__ = [
    "InjectionMarkerError",
    "WebSnippetPolicyError",
    "detect_snippet_injection_markers",
    "validate_snippet_domain",
    "wrap_web_snippet",
]
