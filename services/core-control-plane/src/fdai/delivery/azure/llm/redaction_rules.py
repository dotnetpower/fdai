"""Model-input redaction rules shared by every provider adapter.

Each rule finds a secret or an exact identifier in text bound for a model. A secret
key's value that swallowed a following key is extended over that key's own value, and
every rule is applied in one linear pass.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

REDACTED: Final[str] = "[REDACTED]"
# A secret key, including a compound key such as client_secret, DB_PASSWORD, or AccountKey.
# A short prefix is matched with the key; after a longer identifier the match starts at the
# keyword itself, so matching stays linear and no prefix length hides a key.
_SENSITIVE_KEY: Final[str] = (
    r"(?i)(?:(?<![a-z0-9])(?:[a-z0-9][a-z0-9_.-]{0,63}?)?|(?<=[a-z0-9_.-]))"
    r"(?:password|(?<!/etc/)passwd|pwd|secret|token|api[ \t_-]{0,2}key|credentials?"
    r"|(?:account|access|shared[ \t_-]{0,2}access|client|private)[ \t_-]{0,2}key"
    r"|connection[ \t_-]{0,2}string|비밀번호|암호|토큰)"
    # A value-like trailing component, as in passwordValue or secret_data, is the same key.
    r"(?:[ \t_.-]{0,2}(?:value|val|data|string|str|text|hash|plain|raw))?"
)

_SENSITIVE_NAME: Final[str] = _SENSITIVE_KEY + r"(?:\\{0,7}[\"'])?\s*[:=]\s*"

# A backslash ends a value only when it escapes a quote, never before another JSON escape.
_VALUE_END: Final[str] = r"(?=$|[\s,;\"'}]|\\{1,8}[\"'])"

# A quoted value runs to the quote that opened it, so a passphrase with spaces or the other
# quote kind stays whole, and an empty quoted string before it does not hide it. An unquoted
# value that is exactly a JSON or YAML boolean or null literal or already redacted is not a
# secret, and neither is a JSON object or array whose first member is a quoted string, or an
# empty one. Escaped quotes still delimit a value.
_SENSITIVE_VALUE: Final[str] = (
    r"(?:\\{0,7}([\"'])(?:\\{0,7}\1)?(?!\[REDACTED\]\\{0,7}\1)"
    r"(?:(?!\\{0,7}\1)[^\\\n]|\\(?!\\{0,6}[\"']))+"
    r"|(?!\[REDACTED\]"
    + _VALUE_END
    + r"|(?:true|false|null|none|yes|no|on|off)"
    + _VALUE_END
    + r"|[{\[]\s*\\{0,7}[\"']|(?:\[\s*\]|\{\s*\})"
    + _VALUE_END
    + r")"
    r"(?:[^\s,;\"'}\\]|\\(?!\\{0,6}[\"']))+)"
)

# In raw operator text, a secret key whose unquoted value opens an object or array holds
# its secret inside; a quoted value that starts with a bracket is a string instead.
SENSITIVE_CONTAINER: Final[re.Pattern[str]] = re.compile(_SENSITIVE_NAME + r"(?=[{\[])")

# A key that a matched value swallowed, as in pwd=a&token= x, with or without its
# separator; its own value follows and is matched again from that key. The key must end
# within a bounded window before the match end, which keeps the search linear.
_SWALLOWED_NAME: Final[re.Pattern[str]] = re.compile(
    _SENSITIVE_KEY + r"(?:\\{0,7}[\"'])?(?:\s{0,8}[:=]\s{0,8})?\Z"
)

_SWALLOWED_WINDOW: Final[int] = 160

REDACTION_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("inline-image", re.compile(r"(?i)data:image/[a-z0-9.+-]+;base64,[a-z0-9+/=_\r\n-]+")),
    (
        "bearer-token",
        re.compile(
            r"(?i)(?:(?<![a-z0-9_])bearer\s+"
            r"|authorization\s*[:=]\s*(?:basic|digest|negotiate)\s+)[a-z0-9._~+/=-]+"
        ),
    ),
    ("named-secret", re.compile(_SENSITIVE_NAME + _SENSITIVE_VALUE)),
    # ASCII lookarounds instead of \b, so an adjacent Korean particle cannot hide the value.
    ("jwt", re.compile(r"(?<![A-Za-z0-9_])eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")),
    ("azure-resource-id", re.compile(r"(?i)/subscriptions/[0-9a-f-]+(?:/[^\s\"'<>]+)+")),
    (
        "guid",
        re.compile(
            r"(?i)(?<![0-9a-f])"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"(?![0-9a-f])"
        ),
    ),
    (
        "email",
        re.compile(
            r"(?i)(?<![a-z0-9.!#$%&'*+/=?^_`{|}~-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+"
            r"@[a-z0-9.-]+\.[a-z]{2,}(?![a-z0-9])"
        ),
    ),
    ("ip-address", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
    ("url", re.compile(r"(?i)https?://[^\s\"'<>]+")),
    ("sas-value", re.compile(r"(?i)(?:\?|&)(?:sig|se|sp|sv|st|spr)=[^&\s\"'<>]+")),
)

# Rules that hide exact identifiers rather than secrets; a caller may substitute an opaque
# placeholder for these values instead of dropping them.
IDENTITY_RULES: Final[frozenset[str]] = frozenset(
    {"azure-resource-id", "guid", "email", "ip-address", "url"}
)


def replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace ordered, non-overlapping spans with the redaction marker in one pass."""

    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.extend((text[cursor:start], REDACTED))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def rule_spans(rule: str, pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    """Return the spans one rule removes; a secret value that swallowed a key extends."""

    if rule != "named-secret":
        return [match.span() for match in pattern.finditer(text)]
    spans: list[tuple[int, int]] = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        start, end = match.span()
        while (
            (inner := _SWALLOWED_NAME.search(text, max(start + 1, end - _SWALLOWED_WINDOW), end))
            is not None
            and (follow := pattern.match(text, inner.start())) is not None
            and follow.end() > end
        ):
            end = follow.end()
        spans.append((start, end))
        position = end
    return spans


def redact(value: str) -> tuple[str, Counter[str]]:
    """Return ``value`` with every rule applied and the count of replacements per rule."""

    output = value
    redactions: Counter[str] = Counter()
    for rule, pattern in REDACTION_RULES:
        spans = rule_spans(rule, pattern, output)
        if spans:
            output = replace_spans(output, spans)
            redactions[rule] += len(spans)
    return output, redactions


__all__ = [
    "IDENTITY_RULES",
    "REDACTED",
    "REDACTION_RULES",
    "SENSITIVE_CONTAINER",
    "redact",
    "replace_spans",
    "rule_spans",
]
