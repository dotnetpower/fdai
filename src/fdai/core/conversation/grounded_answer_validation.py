"""Validate low-ambiguity claims added by grounded answer narration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from fdai.core.conversation.tools import ToolResult

_TIMESTAMP_RE: Final = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\b"
)
_NUMBER_RE: Final = re.compile(r"(?<![\w.-])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?(?![\w.-])")
_IDENTIFIER_RE: Final = re.compile(
    r"\b(?:ops|remediate|governance|tool)\.[a-z0-9]+(?:-[a-z0-9]+)+\b"
    r"|\b(?:corr|evt|event|inc|incident|rule)-[A-Za-z0-9_.:-]*[A-Za-z0-9_]\b"
)
_FRESHNESS_RE: Final = re.compile(
    r"\b(?:current|currently|live|latest|now|as\s+of)\b|현재|실시간|최신|지금|기준",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GroundedAnswerValidation:
    valid: bool
    reason_code: str | None = None


def validate_grounded_answer(answer: str, result: ToolResult) -> GroundedAnswerValidation:
    """Reject unsupported exact values while leaving qualitative prose untouched."""

    if any(reference not in answer for reference in result.evidence_refs):
        return GroundedAnswerValidation(False, "missing_evidence_reference")
    authority = _authority_text(result)
    if authority is None:
        return GroundedAnswerValidation(False, "authority_not_serializable")
    answer_timestamps, answer_numbers = _atomic_values(answer)
    answer_identifiers = frozenset(match.group(0) for match in _IDENTIFIER_RE.finditer(answer))
    authority_identifiers = frozenset(
        match.group(0) for match in _IDENTIFIER_RE.finditer(authority)
    )
    if not answer_identifiers.issubset(authority_identifiers):
        return GroundedAnswerValidation(False, "unsupported_identifier")
    authority_timestamps, authority_numbers = _atomic_values(authority)
    if not answer_timestamps.issubset(authority_timestamps):
        return GroundedAnswerValidation(False, "unsupported_timestamp")
    if not answer_numbers.issubset(authority_numbers):
        return GroundedAnswerValidation(False, "unsupported_numeric_value")
    if _FRESHNESS_RE.search(answer) and not answer_timestamps:
        return GroundedAnswerValidation(False, "freshness_without_timestamp")
    return GroundedAnswerValidation(True)


def has_authoritative_timestamp(result: ToolResult) -> bool:
    authority = _authority_text(result)
    return authority is not None and bool(_TIMESTAMP_RE.search(authority))


def _authority_text(result: ToolResult) -> str | None:
    try:
        return json.dumps(
            {
                "preview": result.preview,
                "data": result.data,
                "evidence_refs": result.evidence_refs,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None


def _atomic_values(text: str) -> tuple[frozenset[str], frozenset[str]]:
    timestamps = frozenset(match.group(0) for match in _TIMESTAMP_RE.finditer(text))
    without_timestamps = _TIMESTAMP_RE.sub(" ", text)
    numbers = frozenset(
        normalized
        for match in _NUMBER_RE.finditer(without_timestamps)
        if (normalized := _normalize_number(match.group(0))) is not None
    )
    return timestamps, numbers


def _normalize_number(raw: str) -> str | None:
    percentage = raw.endswith("%")
    value = raw[:-1] if percentage else raw
    try:
        normalized = format(Decimal(value.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return None
    if normalized == "-0":
        normalized = "0"
    return normalized + ("%" if percentage else "")


__all__ = [
    "GroundedAnswerValidation",
    "has_authoritative_timestamp",
    "validate_grounded_answer",
]
