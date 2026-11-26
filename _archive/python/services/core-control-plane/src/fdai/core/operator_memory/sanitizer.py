"""Sanitize + wrap operator-memory bodies for prompt injection.

The retrieved body is **data**, not instructions. Two defenses layer:

1. :func:`detect_injection_markers` scans the body for common prompt
   -injection patterns ("ignore previous", "system:", role-hijack
   attempts). A hit fails closed so the entry is quarantined at
   write time before it can reach a model turn.
2. :func:`wrap_operator_note` renders every accepted body inside an
   ``<operator_note trusted="false" ...>...</operator_note>`` tag
   whose ``trusted="false"`` attribute matches the invariant the T2
   base prompt enforces on tool output.

Both helpers are pure functions so any layer of the stack (store
write path, HIL approval workflow, composer inject path) can reuse
the same defense without shared mutable state.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

# Case-insensitive substrings that historically signal prompt
# injection. The list is deliberately conservative; false positives
# route the candidate to a human reviewer, which is the acceptable
# failure mode for an authority-sensitive path.
_INJECTION_MARKERS: Final[tuple[str, ...]] = (
    "ignore previous",
    "ignore the previous",
    "disregard previous",
    "disregard the previous",
    "system:",
    "<|im_start|>",
    "<|im_end|>",
    "you are now",
    "act as ",
    "you must ignore",
    "override the system",
    "reveal your instructions",
    "print your instructions",
    "developer:",
)

# XML meta-characters we escape at wrap time so an entry cannot
# forge the closing tag or inject arbitrary attributes.
_XML_ESCAPES: Final[tuple[tuple[str, str], ...]] = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)

# Zero-width / invisible / bidi-control characters an attacker can splice
# between marker words ("ig<ZWSP>nore previous") to slip a known injection
# phrase past the substring scan. They are stripped from the matching copy
# (never from stored text) before detection. Whitespace (\s) already covers
# NBSP; these are format (Cf) characters \s does NOT match.
_INVISIBLE_CHARS: Final[dict[int, None]] = {
    ord(c): None
    for c in (
        "\u00ad",  # soft hyphen
        "\u200b",  # zero-width space
        "\u200c",  # zero-width non-joiner
        "\u200d",  # zero-width joiner
        "\u200e",  # left-to-right mark
        "\u200f",  # right-to-left mark
        "\u202a",  # left-to-right embedding
        "\u202b",  # right-to-left embedding
        "\u202c",  # pop directional formatting
        "\u202d",  # left-to-right override
        "\u202e",  # right-to-left override
        "\u2060",  # word joiner
        "\u2061",  # function application
        "\u2062",  # invisible times
        "\u2063",  # invisible separator
        "\u2064",  # invisible plus
        "\ufeff",  # BOM / zero-width no-break space
    )
}


class InjectionMarkerError(ValueError):
    """Raised when an operator memory body carries an injection marker.

    Fail-closed: the write path rejects the entry rather than
    quarantining it silently, so a reviewer sees which pattern
    tripped the detector and can rephrase the guidance.
    """

    def __init__(self, markers: tuple[str, ...]) -> None:
        self.markers: tuple[str, ...] = markers
        joined = ", ".join(repr(m) for m in markers)
        super().__init__(f"operator memory body contains injection markers: {joined}")


def detect_injection_markers(body: str) -> tuple[str, ...]:
    """Return every injection marker present in ``body``.

    Empty tuple means the body is safe by this defense. Callers that
    want to fail fast raise :class:`InjectionDetected` from the
    returned tuple.

    The body is lower-cased and its internal whitespace is collapsed to
    single spaces before matching, so trivial obfuscation - extra
    spaces, tabs, or newlines between the marker words
    (``"ignore   previous"``, ``"ignore\\nprevious"``) - cannot slip a
    known injection phrase past the write-time quarantine gate.

    Two further evasions are folded out before matching: the body is
    Unicode NFKC-normalized (so a fullwidth / compatibility homoglyph such
    as ``"\uff49gnore"`` folds to ``"ignore"``) and zero-width / bidi
    format characters are stripped (so ``"ig\u200bnore previous"``, which
    renders as a readable ``"ignore previous"`` to a model, still matches).
    Normalization is applied to the matching copy only; the stored body is
    never mutated.
    """

    if not body:
        return ()
    folded = unicodedata.normalize("NFKC", body).translate(_INVISIBLE_CHARS)
    normalized = re.sub(r"\s+", " ", folded.lower())
    hits: list[str] = []
    for marker in _INJECTION_MARKERS:
        if marker in normalized:
            hits.append(marker)
    return tuple(hits)


def wrap_operator_note(
    *,
    body: str,
    author: str,
    scope_kind: str,
    scope_ref: str,
    category: str,
) -> str:
    """Render an operator memory body inside its trusted="false" envelope.

    Every attribute value is XML-escaped so an attacker cannot
    smuggle attributes or close the tag from inside. The body is
    escaped separately so the sanitizer stays layered - a single
    encoding call covers both attributes and content.
    """

    return (
        f'<operator_note trusted="false" author="{_xml_escape(author)}" '
        f'scope_kind="{_xml_escape(scope_kind)}" '
        f'scope_ref="{_xml_escape(scope_ref)}" '
        f'category="{_xml_escape(category)}">'
        f"{_xml_escape(body)}"
        "</operator_note>"
    )


def _xml_escape(value: str) -> str:
    """Minimal XML entity escape - enough to block tag-forgery and
    attribute-break attempts inside operator note wrappers."""

    escaped = value
    for src, dst in _XML_ESCAPES:
        escaped = escaped.replace(src, dst)
    return escaped


def _dedupe_preserving_order(
    items: Iterable[str],
) -> tuple[str, ...]:  # pragma: no cover - reserved
    """Reserved helper used by later waves that surface all markers to
    the reviewer without repeats."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


__all__ = [
    "InjectionMarkerError",
    "detect_injection_markers",
    "wrap_operator_note",
]
