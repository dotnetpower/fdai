"""Bounded post-generation quality review for Korean narrator prose."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from fdai.delivery.operator_api.application.conversation.verification import (
    AnswerVerification,
    verify_answer,
)

AnswerQualityStatus = Literal[
    "not_applicable",
    "unchanged",
    "rewritten",
    "rejected",
    "unavailable",
    "invalid",
]
AnswerQualityInvoke = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

_MAX_REVIEW_CHARS: Final[int] = 12_000
_MAX_PROTECTED_SPANS: Final[int] = 64
_MAX_EVIDENCE_VALUES: Final[int] = 256
_MAX_EVIDENCE_VALUE_CHARS: Final[int] = 512
_REVIEW_PROMPT: Final[str] = (
    "Review the protected Korean narrator draft and return the required JSON object."
)
_REVIEW_REASONS: Final[frozenset[str]] = frozenset(
    {
        "natural",
        "malformed_word",
        "grammar",
        "repetition",
        "language_mixing",
        "unrepairable",
    }
)
_FENCED_CODE: Final[re.Pattern[str]] = re.compile(r"```[\s\S]*?```")
_INLINE_CODE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]+`")
_URL: Final[re.Pattern[str]] = re.compile(r"https?://[^\s<>()]+")
_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z0-9_./:@-]{3,}(?![A-Za-z0-9_])"
)
_HANGUL: Final[re.Pattern[str]] = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")


@dataclass(frozen=True, slots=True)
class AnswerQualityResult:
    """One bounded quality-review outcome and its final candidate answer."""

    status: AnswerQualityStatus
    answer: str
    reason_code: str
    reviewed: bool
    protected_spans: int = 0
    model: str | None = None
    usage: Mapping[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "reason_code": self.reason_code,
            "reviewed": self.reviewed,
            "protected_spans": self.protected_spans,
            "model": self.model,
        }
        if self.usage is not None:
            payload["usage"] = dict(self.usage)
        return payload


@dataclass(frozen=True, slots=True)
class _ProtectedDraft:
    text: str
    tokens: tuple[tuple[str, str], ...]


async def review_korean_narrator_answer(
    *,
    answer: str,
    view_context: Mapping[str, Any],
    locale: str | None,
    invoke: AnswerQualityInvoke,
) -> AnswerQualityResult:
    """Review Korean narrator prose once while preserving evidence exactly."""

    if _primary_locale(locale) != "ko" or not answer.strip() or not _HANGUL.search(answer):
        return _result("not_applicable", answer, "quality_not_applicable", reviewed=False)
    if len(answer) > _MAX_REVIEW_CHARS:
        return _result("unavailable", answer, "quality_answer_too_large", reviewed=False)

    protected = _protect_draft(answer, view_context)
    quality_context: dict[str, Any] = {
        "routeId": "answer-quality-review",
        "purpose": "Proofread Korean narrator prose without changing protected evidence.",
        "facts": [
            {"key": "target_locale", "value": "ko"},
            {"key": "protected_span_count", "value": len(protected.tokens)},
        ],
        "records": {"draft": [{"text": protected.text}]},
        "_answer_quality_review": True,
    }
    try:
        reply = await invoke(_REVIEW_PROMPT, quality_context)
    except Exception:  # noqa: BLE001 - quality review degrades to factual verification
        return _result(
            "unavailable",
            answer,
            "quality_reviewer_unavailable",
            reviewed=True,
            protected_spans=len(protected.tokens),
        )

    model = reply.get("model") if isinstance(reply.get("model"), str) else None
    usage = _usage(reply.get("usage"))
    content = reply.get("answer")
    if not isinstance(content, str):
        return _result(
            "invalid",
            answer,
            "quality_review_invalid_response",
            reviewed=True,
            protected_spans=len(protected.tokens),
            model=model,
            usage=usage,
        )
    parsed = _review_payload(content)
    if parsed is None:
        return _result(
            "invalid",
            answer,
            "quality_review_invalid_response",
            reviewed=True,
            protected_spans=len(protected.tokens),
            model=model,
            usage=usage,
        )
    status, reason, reviewed_text = parsed
    if status == "reject":
        return _result(
            "rejected",
            _quality_rejection_answer(locale),
            f"quality_{reason}",
            reviewed=True,
            protected_spans=len(protected.tokens),
            model=model,
            usage=usage,
        )
    if status == "pass" and reviewed_text != protected.text:
        return _result(
            "invalid",
            answer,
            "quality_pass_changed_draft",
            reviewed=True,
            protected_spans=len(protected.tokens),
            model=model,
            usage=usage,
        )
    restored = _restore_protected(reviewed_text, protected.tokens)
    if restored is None:
        return _result(
            "invalid",
            answer,
            "quality_protected_span_mismatch",
            reviewed=True,
            protected_spans=len(protected.tokens),
            model=model,
            usage=usage,
        )
    changed = not _same_text(restored, answer)
    return _result(
        "rewritten" if changed else "unchanged",
        restored,
        f"quality_{reason}",
        reviewed=True,
        protected_spans=len(protected.tokens),
        model=model,
        usage=usage,
    )


def verify_quality_result(
    result: AnswerQualityResult,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification:
    """Run factual verification, or preserve an explicit quality rejection."""

    if result.status == "rejected":
        return AnswerVerification(
            status="unverified",
            answer=result.answer,
            authority="answer_quality_review",
            checks_completed=0,
            checks_total=1,
            reason_code=result.reason_code,
        )
    return verify_answer(result.answer, view_context, locale=locale)


def _protect_draft(answer: str, view_context: Mapping[str, Any]) -> _ProtectedDraft:
    spans = _protected_spans(answer, view_context)
    if not spans:
        return _ProtectedDraft(answer, ())
    digest = hashlib.sha256(answer.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    prefix = f"{{{{FDAI_EVIDENCE_{digest}_"
    while prefix in answer:
        digest = hashlib.sha256(digest.encode()).hexdigest()[:12]
        prefix = f"{{{{FDAI_EVIDENCE_{digest}_"
    pieces: list[str] = []
    tokens: list[tuple[str, str]] = []
    cursor = 0
    for index, (start, end) in enumerate(spans):
        token = f"{prefix}{index:03d}}}}}"
        pieces.extend((answer[cursor:start], token))
        tokens.append((token, answer[start:end]))
        cursor = end
    pieces.append(answer[cursor:])
    return _ProtectedDraft("".join(pieces), tuple(tokens))


def _protected_spans(answer: str, view_context: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    candidates: set[tuple[int, int]] = set()
    for pattern in (_FENCED_CODE, _INLINE_CODE, _URL):
        candidates.update((match.start(), match.end()) for match in pattern.finditer(answer))
    for match in _IDENTIFIER.finditer(answer):
        value = match.group(0)
        if any(character.isdigit() or character in "._/:@-" for character in value):
            candidates.add((match.start(), match.end()))
    for literal in _evidence_literals(view_context):
        start = 0
        while len(candidates) < _MAX_PROTECTED_SPANS * 4:
            found = answer.find(literal, start)
            if found < 0:
                break
            candidates.add((found, found + len(literal)))
            start = found + len(literal)

    selected: list[tuple[int, int]] = []
    for start, end in sorted(candidates, key=lambda item: (item[0], -(item[1] - item[0]))):
        if selected and start < selected[-1][1]:
            continue
        selected.append((start, end))
        if len(selected) >= _MAX_PROTECTED_SPANS:
            break
    return tuple(selected)


def _evidence_literals(view_context: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    pending: list[Any] = [view_context]
    visited = 0
    while pending and len(values) < _MAX_EVIDENCE_VALUES and visited < 2_000:
        item = pending.pop()
        visited += 1
        if isinstance(item, Mapping):
            pending.extend(item.values())
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            pending.extend(item)
        elif isinstance(item, str):
            normalized = item.strip()
            if 2 <= len(normalized) <= _MAX_EVIDENCE_VALUE_CHARS:
                values.add(normalized)
        elif isinstance(item, int | float) and not isinstance(item, bool):
            values.add(str(item))
    return tuple(sorted(values, key=lambda value: (-len(value), value)))


def _review_payload(content: str) -> tuple[str, str, str] | None:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    status = parsed.get("status")
    reason = parsed.get("reason")
    answer = parsed.get("answer")
    if status not in {"pass", "rewrite", "reject"}:
        return None
    if reason not in _REVIEW_REASONS or not isinstance(answer, str):
        return None
    if status == "reject" and answer:
        return None
    if status != "reject" and not answer.strip():
        return None
    return status, reason, answer


def _restore_protected(text: str, tokens: tuple[tuple[str, str], ...]) -> str | None:
    positions = [text.find(token) for token, _ in tokens]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        return None
    if any(text.count(token) != 1 for token, _ in tokens):
        return None
    if text.count("{{FDAI_EVIDENCE_") != len(tokens):
        return None
    restored = text
    for token, value in tokens:
        restored = restored.replace(token, value)
    return restored


def _same_text(left: str, right: str) -> bool:
    return unicodedata.normalize("NFC", left.strip()) == unicodedata.normalize("NFC", right.strip())


def _primary_locale(locale: str | None) -> str | None:
    if locale is None:
        return None
    return locale.casefold().split("-", 1)[0].split("_", 1)[0]


def _quality_rejection_answer(locale: str | None) -> str:
    if _primary_locale(locale) == "ko":
        return "답변의 한국어 표현 품질을 확인할 수 없어 확정하지 않았습니다. 다시 시도해 주세요."
    return "The answer's language quality could not be confirmed, so it was not finalized."


def _usage(value: Any) -> Mapping[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    normalized = {
        key: item
        for key, item in value.items()
        if isinstance(key, str)
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }
    return normalized or None


def _result(
    status: AnswerQualityStatus,
    answer: str,
    reason_code: str,
    *,
    reviewed: bool,
    protected_spans: int = 0,
    model: str | None = None,
    usage: Mapping[str, int] | None = None,
) -> AnswerQualityResult:
    return AnswerQualityResult(
        status=status,
        answer=answer,
        reason_code=reason_code,
        reviewed=reviewed,
        protected_spans=protected_spans,
        model=model,
        usage=usage,
    )


__all__ = [
    "AnswerQualityInvoke",
    "AnswerQualityResult",
    "AnswerQualityStatus",
    "review_korean_narrator_answer",
    "verify_quality_result",
]
