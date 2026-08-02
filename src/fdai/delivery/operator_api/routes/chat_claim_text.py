"""Text parsing and normalization primitives for screen claims."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

ID_RE: Final = re.compile(
    r"\b(?:ops|remediate|governance|tool)\.[a-z0-9]+(?:-[a-z0-9]+)+\b"
    r"|\b(?:corr|evt|event|inc|incident|rule)-[A-Za-z0-9_.:-]*[A-Za-z0-9_]\b"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
TIMESTAMP_RE: Final = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)
PERCENT_RE: Final = re.compile(
    r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*(?:%|percent(?:age)?\b|퍼센트)",
    re.IGNORECASE,
)
NUMBER_RE: Final = re.compile(
    r"(?<![\w.-])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?![A-Za-z0-9_-])"
)
WORD_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,}|[\uac00-\ud7a3]{2,}")
ANCHOR_STOP: Final = frozenset(
    {
        "about",
        "answer",
        "because",
        "current",
        "from",
        "latest",
        "only",
        "screen",
        "shows",
        "that",
        "there",
        "this",
        "value",
        "with",
    }
)


def normalize_claim_value(kind: str, raw: str) -> str | None:
    if kind == "timestamp":
        return normalize_timestamp(raw)
    if kind == "percentage":
        value = re.sub(r"(?:%|percent(?:age)?|퍼센트)", "", raw, flags=re.I)
        return normalize_number(value)
    if kind == "number":
        return normalize_number(raw)
    return raw


def normalize_number(raw: str) -> str | None:
    number = decimal_value(raw.replace(",", "").strip())
    if number is None:
        return None
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def decimal_value(raw: str) -> Decimal | None:
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def normalize_timestamp(raw: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return raw
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_text(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw).casefold().split())


def anchors(raw: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", raw)
    camel_split = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", normalized)
    token_source = re.sub(r"[_.-]+", " ", camel_split)
    return tuple(
        sorted(
            {
                anchor_token(token)
                for token in WORD_RE.findall(token_source)
                if anchor_token(token) not in ANCHOR_STOP
            }
        )
    )


def anchor_token(raw: str) -> str:
    token = raw.casefold()
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def anchor_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return bool(set(left) & set(right))


def anchor_score(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    return len(set(left) & set(right))


def overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
