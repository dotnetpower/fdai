"""Sanitize + wrap web snippets for prompt injection (Wave 5 alpha).

Web-retrieved text is **data**, not instructions. Three defenses
layer here:

1. :func:`detect_snippet_injection_markers` - reuses the same
   marker list :mod:`fdai.core.operator_memory.sanitizer`
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

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from fdai.core.operator_memory.sanitizer import (
    InjectionMarkerError,
    detect_injection_markers,
)
from fdai.core.web_search.types import WebSearchResult, WebSnippet

_XML_ESCAPES: Final[tuple[tuple[str, str], ...]] = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)

#: Only these URL schemes may originate a web snippet. ``javascript:`` /
#: ``file:`` / ``data:`` have no network host and would smuggle a
#: scheme-confusion payload into the audit / replay surface.
_ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

#: Default cap on the rendered snippet body. A provider is asked to respect
#: ``max_results`` but nothing bounds a single snippet's size; without a cap
#: one megabyte-scale snippet blows the T2 context window and cost. The cap
#: is applied at wrap time (after the full-body injection scan) so a marker
#: hiding past the cut is still caught.
_DEFAULT_MAX_BODY_CHARS: Final[int] = 8_000
_TRUNCATION_MARKER: Final[str] = "...[truncated]"


class WebSnippetPolicyError(ValueError):
    """Raised when a snippet violates a sanitization policy.

    Structured with a stable ``code`` so a caller can dispatch on
    it for telemetry without pattern-matching on error messages.
    Codes:

    - ``off_allowlist`` - the snippet URL's host is not on the query's
      allowlist;
    - ``empty_allowlist`` - the query supplied an empty allowlist
      (the caller MUST populate it before shipping snippets into a
      prompt);
    - ``invalid_url`` - the snippet ``url`` is not a well-formed
      ``http(s)`` URL with a host (a ``javascript:`` / ``file:`` /
      ``data:`` URL, or a URL with no host);
    - ``domain_url_mismatch`` - the denormalized ``domain`` field does
      not match the URL's actual host (a provider cannot present an
      allowlisted label while linking elsewhere);
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


def _snippet_host(url: str) -> str | None:
    """Return the lowercased host of an ``http(s)`` URL, else ``None``.

    ``None`` signals an unusable URL (a non-``http(s)`` scheme or a
    hostless URL); the caller fails closed. A trailing FQDN dot is
    stripped so ``docs.example.com.`` compares equal to
    ``docs.example.com``.
    """

    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    return host or None


def validate_snippet_domain(
    *,
    snippet: WebSnippet,
    allowed_domains: tuple[str, ...],
) -> None:
    """Refuse a snippet whose actual source is not on the allowlist.

    The allowlist is checked against the **host parsed from
    ``snippet.url``**, not the provider-supplied ``domain`` label - a
    hostile or buggy provider must not be able to present an allowlisted
    ``domain`` while linking to an off-allowlist URL. The ``domain``
    field is then required to agree with that host.

    Empty ``allowed_domains`` is itself a policy failure - the caller
    MUST populate the allowlist BEFORE receiving snippets; an empty
    tuple means the snippet has no legitimate source.
    """

    if not allowed_domains:
        raise WebSnippetPolicyError(
            "empty_allowlist",
            "allowed_domains is empty; a snippet cannot legitimately reach the prompt",
        )
    host = _snippet_host(snippet.url)
    if host is None:
        raise WebSnippetPolicyError(
            "invalid_url",
            f"snippet url {snippet.url!r} is not a valid http(s) URL with a host",
        )
    allowlist = {d.lower().rstrip(".") for d in allowed_domains}
    if host not in allowlist:
        raise WebSnippetPolicyError(
            "off_allowlist",
            f"snippet url host {host!r} is not in the allowlist {allowed_domains!r}",
        )
    if snippet.domain.lower().rstrip(".") != host:
        raise WebSnippetPolicyError(
            "domain_url_mismatch",
            f"snippet domain {snippet.domain!r} does not match its url host {host!r}",
        )



def wrap_web_snippet(
    *,
    snippet: WebSnippet,
    allowed_domains: tuple[str, ...],
    max_body_chars: int = _DEFAULT_MAX_BODY_CHARS,
) -> str:
    """Render a snippet inside its ``trusted="false"`` envelope.

    Runs both defenses first (domain allowlist + injection markers) and
    only then wraps the body. The **full** body is scanned for injection
    markers before any truncation, so a marker hiding past
    ``max_body_chars`` is still caught; the rendered body is then bounded
    to ``max_body_chars`` (plus a truncation marker) to keep one oversized
    snippet from blowing the T2 context / cost budget. XML meta-characters
    in attribute values and body are escaped so a snippet cannot forge the
    closing tag or inject arbitrary attributes.

    Raises:
        WebSnippetPolicyError: domain not on allowlist / allowlist empty /
            invalid url / domain-url mismatch.
        InjectionMarkerError: body carries at least one injection marker.
        ValueError: ``max_body_chars`` is not positive.
    """

    if max_body_chars < 1:
        raise ValueError("max_body_chars MUST be >= 1")
    validate_snippet_domain(snippet=snippet, allowed_domains=allowed_domains)
    markers = detect_snippet_injection_markers(snippet.text)
    if markers:
        raise InjectionMarkerError(markers)
    body = snippet.text
    if len(body) > max_body_chars:
        body = body[:max_body_chars] + _TRUNCATION_MARKER
    return (
        '<web_snippet trusted="false" '
        f'url="{_xml_escape(snippet.url)}" '
        f'domain="{_xml_escape(snippet.domain)}" '
        f'content_hash="{_xml_escape(snippet.content_hash)}">'
        f"{_xml_escape(body)}"
        "</web_snippet>"
    )


def _xml_escape(value: str) -> str:
    escaped = value
    for src, dst in _XML_ESCAPES:
        escaped = escaped.replace(src, dst)
    return escaped


@dataclass(frozen=True, slots=True)
class SanitizedWebResult:
    """Outcome of sanitizing a whole :class:`WebSearchResult`.

    ``wrapped`` holds the ``trusted="false"`` envelopes of every snippet
    that passed all defenses, ready to inject into a T2 turn. ``dropped``
    records ``(content_hash, reason_code)`` for every snippet that was
    refused, so the audit log names exactly why a snippet did not reach
    the prompt.
    """

    wrapped: tuple[str, ...]
    dropped: tuple[tuple[str, str], ...]


def sanitize_web_result(
    result: WebSearchResult,
    *,
    max_body_chars: int = _DEFAULT_MAX_BODY_CHARS,
) -> SanitizedWebResult:
    """Validate + wrap every snippet in a result - the safe default path.

    This is the "safe path is the easy path" entry point: instead of a
    caller remembering to call :func:`validate_snippet_domain` and
    :func:`wrap_web_snippet` per snippet (and forgetting on one), it hands
    the whole :class:`WebSearchResult` here and gets back only clean,
    allowlisted, size-capped, ``trusted="false"`` envelopes.

    Fail-closed per snippet: a snippet that fails any defense (off
    allowlist, invalid URL, domain/url mismatch, injection marker) is
    dropped with a structured reason and NEVER reaches ``wrapped`` - one
    hostile snippet cannot poison the clean ones. The result is also
    capped at ``result.query.max_results`` so a provider that ignored the
    contract and returned more snippets cannot fan out the prompt.
    """

    allowed = result.query.allowed_domains
    wrapped: list[str] = []
    dropped: list[tuple[str, str]] = []
    for snippet in result.snippets[: result.query.max_results]:
        try:
            envelope = wrap_web_snippet(
                snippet=snippet,
                allowed_domains=allowed,
                max_body_chars=max_body_chars,
            )
        except WebSnippetPolicyError as exc:
            dropped.append((snippet.content_hash, exc.code))
            continue
        except InjectionMarkerError:
            dropped.append((snippet.content_hash, "injection_markers_detected"))
            continue
        wrapped.append(envelope)
    return SanitizedWebResult(wrapped=tuple(wrapped), dropped=tuple(dropped))


__all__ = [
    "InjectionMarkerError",
    "SanitizedWebResult",
    "WebSnippetPolicyError",
    "detect_snippet_injection_markers",
    "sanitize_web_result",
    "validate_snippet_domain",
    "wrap_web_snippet",
]
