"""Detection-only views of text bound for a model.

These helpers find exact identifiers to mask, secrets in raw operator text, and secrets
or identifiers that only decoding, normalization, or record structure reveals. A caller
that must not send such text holds the call. No detection copy is ever sent anywhere.
"""

from __future__ import annotations

import html
import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from typing import Final
from urllib.parse import unquote

from fdai.delivery.azure.llm.redaction_rules import (
    IDENTITY_RULES,
    REDACTION_RULES,
    SENSITIVE_CONTAINER,
    redact,
    replace_spans,
    rule_spans,
)

# One escape per match, read left to right, so an escaped backslash is decoded before the
# character after it and each nested layer decodes exactly once.
_ESCAPE: Final[re.Pattern[str]] = re.compile(
    r"\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{1,4})|([nrt])|([\"'\\/]))"
)

# A code-point escape under any number of backslashes, for the depth-agnostic copy.
_DEEP_ESCAPE: Final[re.Pattern[str]] = re.compile(
    r"\\+(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{1,4}))"
)

_MAX_DETECTION_ROUNDS: Final[int] = 8

_MAX_DETECTION_BRANCHES: Final[int] = 6

_SKELETON_DROPPED: Final[frozenset[str]] = frozenset({"Mn", "Mc", "Me", "Cf", "Cc"})

_LAYOUT_CONTROLS: Final[frozenset[str]] = frozenset("\n\r\t")

# A record whose label field names a sensitive setting keeps its value in a sibling field,
# as app settings and deployment parameters do, so the label alone marks the record.
_SENSITIVE_WORD: Final[str] = (
    r"(?:password|passwd|pwd|secret|token|api[ \t_-]{0,2}key|credentials?"
    r"|(?:account|access|shared[ \t_-]{0,2}access|client|private)[ \t_-]{0,2}key"
    r"|connection[ \t_-]{0,2}string|비밀번호|암호|토큰)"
)

# A label field, including a compound one such as settingName or env_var_key.
_LABEL_FIELD: Final[str] = (
    r"(?:[a-z0-9]{0,24}[_-]?)?"
    r"(?:name|key|label|setting|parameter|param|field|variable|var|env|property)"
    r"(?:[_-]?(?:name|key|id))?"
)

# The sensitive word must be a whole label component, as in DB_PASSWORD or dbPassword, so
# labels such as a tokenizer setting do not match.
_WORD_START: Final[str] = r"(?:(?<![A-Za-z0-9])|(?<=[a-z0-9])(?-i:(?=[A-Z])))"
# After the word, a lowercase letter continues it; an uppercase one starts the next part.
_WORD_END: Final[str] = r"(?-i:s?(?![a-z]))"
# A label that names a reference, a flag, or a policy about a secret, such as secretName or
# passwordPolicy, does not hold the secret itself.
_REFERENCE_SUFFIX: Final[str] = (
    r"(?![ \t_.-]?(?:name|ref|reference|id|uri|url|version|expiry|expiration|expires|length"
    r"|count|enabled|disabled|policy|type|rotation|ttl|required)(?![a-z]))"
)
# A label field, quoted or not, in flow or block style, whose value names a sensitive setting.
_SENSITIVE_LABEL: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![a-z0-9_])[\"']?"
    + _LABEL_FIELD
    + r"[\"']?\s*[:=]\s*[\"']?[^\"'\n,{}]{0,256}?"
    + _WORD_START
    + _SENSITIVE_WORD
    + _WORD_END
    + _REFERENCE_SUFFIX
)
# The same record must also carry a value-bearing sibling field for the label to mark a
# secret; a record ends at a brace or at the next item of a block list.
_VALUE_FIELD: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![a-z0-9_])[\"']?(?:value|data|content)[\"']?\s*[:=]\s*[\"']?(?P<value>[^\"'\n,}]*)"
)
# A boolean, null, or numeric sibling value is a flag or a counter, not a secret.
_PLAIN_VALUE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\s*(?:true|false|yes|no|on|off|null|none|-?\d+(?:\.\d+)?)?\s*"
)
_RECORD_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"[{}]|\n[ \t]*-[ \t]")

_MAX_CONTAINER_CHARS: Final[int] = 4096

_MAX_CONTAINERS: Final[int] = 64

_SEGMENT_TRAILERS: Final[frozenset[str]] = frozenset(".,;:!?)]}`*|~'\"")

_SEGMENT_LEADERS: Final[frozenset[str]] = frozenset("`*|~'\"")

_EMAIL_KEY_SEPARATORS: Final[frozenset[str]] = frozenset("=?#&")

_SEGMENT_OPENERS: Final[dict[str, str]] = {
    ")": "(",
    "]": "[",
    "}": "{",
    "`": "`",
    "*": "*",
    "~": "~",
    "|": "|",
    "'": "'",
    '"': '"',
}


def identity_segments(text: str) -> tuple[tuple[int, int], ...]:
    """Return the merged spans that identity redaction rules would replace in ``text``.

    A trailing run of non-ASCII characters is released only when it follows a word or a
    closing wrapper whose opener precedes the identifier, as the particle in ``vm-01의``
    does; text after a separator such as / or =, and any part of a secret value, stays
    inside. Sentence punctuation and Markdown wrapping that a greedy rule swallows are
    trimmed from both ends, and an email starts after any ``key=`` prefix.
    """

    secrets: list[list[tuple[int, int]]] = []

    def secret_hidden() -> list[tuple[int, int]]:
        if not secrets:
            secrets.append(_merged(secret_spans(text)))
        return secrets[0]

    spans = sorted(
        (start, _segment_end(text, match, start, secret_hidden))
        for rule, pattern in REDACTION_RULES
        if rule in IDENTITY_RULES
        for match in pattern.finditer(text)
        for start in (_trim_leaders(text, _rule_start(rule, text, match), match.end()),)
    )
    spans = [(start, end) for start, end in spans if end > start]
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


def identity_matches(text: str) -> tuple[tuple[int, int], ...]:
    """Return the untrimmed spans of every identity rule match in ``text``."""

    return tuple(
        (match.start(), match.end())
        for rule, pattern in REDACTION_RULES
        if rule in IDENTITY_RULES
        for match in pattern.finditer(text)
    )


def detection_copies(text: str) -> tuple[tuple[str, ...], bool]:
    """Return every copy of ``text`` a secret check must scan, and whether decoding finished.

    Each round decodes one escape layer, HTML entities, and percent escapes, composes
    surrogate pairs, applies compatibility normalization, and removes invisible formatting
    characters, so a character that one decoder introduces is still normalized by the
    next round. Rounds repeat to a fixed point within a bound; the final copy also gets
    every code-point escape decoded whatever its depth, and all backslashes removed. A
    caller that holds on detection checks every copy and holds when decoding does not
    finish. No copy is ever sent anywhere.
    """

    copies, complete = _fixed_point(text)
    pending = [copies[-1]]
    seen = {copies[-1]}
    branches = 0
    # Each new variant runs to its own fixed point, and a variant that still has
    # backslashes spawns its own variants, within a bound on the number of branches.
    while pending:
        final = pending.pop()
        if "\\" not in final:
            continue
        for variant in (_DEEP_ESCAPE.sub(_decoded_escape, final), final.replace("\\", "")):
            if variant in seen:
                continue
            if branches == _MAX_DETECTION_BRANCHES:
                return tuple(dict.fromkeys(copies)), False
            branches += 1
            more, done = _fixed_point(variant)
            copies.extend(more)
            complete = complete and done
            seen.add(variant)
            if more[-1] not in seen:
                seen.add(more[-1])
                pending.append(more[-1])
    # A mark or control character inserted into a key survives normalization, so every copy
    # also gets a skeleton without them; Hangul recomposes, and no skeleton is ever sent.
    copies.extend([_skeleton(copy) for copy in copies])
    return tuple(dict.fromkeys(copies)), complete


def _skeleton(text: str) -> str:
    """Return a detection-only copy without marks or controls; layout becomes a space."""

    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(
        " " if item in _LAYOUT_CONTROLS else item
        for item in decomposed
        if item in _LAYOUT_CONTROLS or unicodedata.category(item) not in _SKELETON_DROPPED
    )
    return unicodedata.normalize("NFC", kept)


def _fixed_point(text: str) -> tuple[list[str], bool]:
    """Return ``text`` and every canonical round of it, and whether the rounds converged."""

    copies = [text]
    current = text
    for _ in range(_MAX_DETECTION_ROUNDS):
        step = _canonical_round(current)
        if step == current:
            return copies, True
        copies.append(step)
        current = step
    return copies, False


def _canonical_round(text: str) -> str:
    decoded = unquote(html.unescape(_ESCAPE.sub(_decoded_escape, text)))
    try:
        decoded = decoded.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        pass
    normalized = unicodedata.normalize("NFKC", decoded)
    return "".join(item for item in normalized if unicodedata.category(item) != "Cf")


def _decoded_escape(match: re.Match[str]) -> str:
    point = match[1] or match[2] or match[3]
    if point is not None:
        code = int(point, 16)
        # An impossible code point stays undecoded, so the copy never hides it.
        return chr(code) if code <= 0x10FFFF else match[0]
    if match[4] is not None:
        return " "
    return match[5]


def labels_secret(text: str) -> bool:
    """Return whether a structured record labels a sensitive setting next to its value.

    A label field whose value names a sensitive setting marks the record only when a
    value-bearing field sits in the same record, as in app settings, environment
    variables, and deployment parameters.
    """

    cursor = 0
    for boundary in (*_RECORD_BOUNDARY.finditer(text), None):
        end = boundary.start() if boundary is not None else len(text)
        record = text[cursor:end]
        if _SENSITIVE_LABEL.search(record) and any(
            not _PLAIN_VALUE.fullmatch(value["value"]) for value in _VALUE_FIELD.finditer(record)
        ):
            return True
        cursor = boundary.end() if boundary is not None else end
    return False


def secret_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return every span of raw text that holds a secret.

    This adds, to every non-identity redaction rule, a secret key whose value opens an
    object or array, because raw operator text can carry a secret inside one.
    """

    return (
        *(
            span
            for rule, pattern in REDACTION_RULES
            if rule not in IDENTITY_RULES
            for span in rule_spans(rule, pattern, text)
        ),
        *_container_spans(text),
    )


def redact_text(text: str) -> str:
    """Return raw ``text`` with every secret container and then every redaction rule applied.

    Each container is replaced from its opener, so its key stays for the rules, which then
    skip the replaced value and remove everything else they would remove.
    """

    output = replace_spans(text, _merged(_container_spans(text, from_opener=True)))
    return redact(output)[0]


def _merged(spans: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _container_spans(text: str, *, from_opener: bool = False) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for count, match in enumerate(SENSITIVE_CONTAINER.finditer(text)):
        start = match.end() if from_opener else match.start()
        if count == _MAX_CONTAINERS:
            # Too many openers to bound one by one, so everything after them is withheld.
            spans.append((start, len(text)))
            break
        end = _container_end(text, match.end())
        # A value that continues past its closer, as in []abc, is one value.
        while end < len(text) and not text[end].isspace() and text[end] not in ",;\"'}\\":
            end += 1
        spans.append((start, end))
    return tuple(spans)


def _container_end(text: str, start: int) -> int:
    """Return the end of the balanced object or array at ``start``.

    Brackets inside quoted strings do not count, and a mismatched closer or a container
    longer than the bound withholds the rest of the text.
    """

    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for index in range(start, min(len(text), start + _MAX_CONTAINER_CHARS)):
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in "\"'":
            quote = character
        elif character in "{[":
            stack.append("}" if character == "{" else "]")
        elif character in "}]":
            if not stack or stack.pop() != character:
                return len(text)
            if not stack:
                return index + 1
    return len(text)


def _segment_end(
    text: str,
    match: re.Match[str],
    start: int,
    secrets: Callable[[], list[tuple[int, int]]],
) -> int:
    """Return the span end after trailing punctuation and a final non-ASCII run.

    Punctuation is trimmed first, so a particle before a question mark, as in
    ``vm-01은?``, is still released; non-ASCII text followed by more ASCII, such as a
    localized path segment before a query string, stays inside the span. Nothing that
    is part of a secret value is ever trimmed or released.
    """

    raw_end = match.end()
    end = _trim_trailers(text, start, raw_end)
    if end < raw_end and (cut := _overlapping(secrets(), end, raw_end)) is not None:
        return min(raw_end, max(end, cut[1]))
    released = end
    while released > start and not text[released - 1].isascii():
        released -= 1
    if (
        start < released < end
        and _particle_follows(text, start, released - 1)
        and _overlapping(secrets(), released, end) is None
    ):
        end = _trim_trailers(text, start, released)
    return end


def _overlapping(spans: list[tuple[int, int]], low: int, high: int) -> tuple[int, int] | None:
    """Return a span of the sorted, disjoint ``spans`` that overlaps ``[low, high)``."""

    index = bisect_left(spans, (high,)) - 1
    if index >= 0 and spans[index][1] > low:
        return spans[index]
    return None


def contained(inner: list[tuple[int, int]], outer: tuple[tuple[int, int], ...]) -> bool:
    """Return whether every span of ``inner`` lies inside one span of sorted ``outer``."""

    starts = [start for start, _end in outer]
    for left, right in inner:
        index = bisect_right(starts, left) - 1
        if index < 0 or outer[index][1] < right:
            return False
    return True


def _particle_follows(text: str, start: int, index: int) -> bool:
    """Return whether the character at ``index`` ends a word or a wrapper opened at ``start``.

    A particle attaches to a word or to a closing wrapper whose opener comes right before
    the identifier; after a separator such as / or =, or after ~ inside a path, the text
    is still part of the value.
    """

    character = text[index]
    if character.isascii() and character.isalnum():
        return True
    opener = _SEGMENT_OPENERS.get(character)
    return opener is not None and start > 0 and text[start - 1] == opener


def _rule_start(rule: str, text: str, match: re.Match[str]) -> int:
    start = match.start()
    if rule != "email":
        return start
    at = text.index("@", start, match.end())
    for index in range(at - 1, start - 1, -1):
        if text[index] in _EMAIL_KEY_SEPARATORS:
            return index + 1
    return start


def _trim_leaders(text: str, start: int, end: int) -> int:
    while start < end and text[start] in _SEGMENT_LEADERS:
        start += 1
    return start


def _trim_trailers(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in _SEGMENT_TRAILERS:
        end -= 1
    return end


__all__ = [
    "contained",
    "detection_copies",
    "identity_matches",
    "identity_segments",
    "labels_secret",
    "redact_text",
    "secret_spans",
]
