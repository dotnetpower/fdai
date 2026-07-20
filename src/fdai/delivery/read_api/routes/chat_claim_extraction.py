"""Extract bounded atomic claim drafts from a narrator answer."""

from __future__ import annotations

import re
from typing import Final

from fdai.delivery.read_api.routes.chat_claim_models import ClaimDraft
from fdai.delivery.read_api.routes.chat_claim_text import (
    ID_RE,
    NUMBER_RE,
    PERCENT_RE,
    TIMESTAMP_RE,
    anchors,
    normalize_claim_value,
    normalize_text,
    overlaps,
)

MAX_CLAIMS: Final = 64
CAUSAL_RE: Final = re.compile(
    r"\b(?:because|due to|caused by|resulted from|reason is)\b"
    r"|\ub54c\ubb38|\uc6d0\uc778\uc740|\uc6d0\uc778\uc774|\uc774\uc720\ub294",
    re.IGNORECASE,
)
SCOPE_RE: Final = re.compile(
    r"\b(?:no|none)\b|\uc5c6\uc2b5\ub2c8\ub2e4|\uc5c6\ub2e4",
    re.IGNORECASE,
)
SCREEN_ABSENCE_RE: Final = re.compile(
    r"\b(?:does not|doesn't|do not|don't)\s+(?:show|provide|include|contain)\b"
    r"|\bno\s+.{1,80}?\s+(?:are\s+|is\s+)?(?:shown|provided|included|present|visible)\b"
    r"|\bnot\s+(?:shown|provided|included|present|visible)\b"
    "|\ubcf4\uc774\uc9c0 \uc54a|\ud45c\uc2dc\ub418\uc9c0 \uc54a"
    "|\uc81c\uacf5\ub418\uc9c0 \uc54a|\ud3ec\ud568\ub418\uc9c0 \uc54a"
    "|\ud3ec\ud568\ub418\uc5b4 \uc788\uc9c0 \uc54a",
    re.IGNORECASE,
)


def extract_claims(answer: str) -> tuple[tuple[ClaimDraft, ...], bool]:
    occupied: list[tuple[int, int]] = []
    drafts: list[ClaimDraft] = []
    for kind, pattern in (
        ("timestamp", TIMESTAMP_RE),
        ("percentage", PERCENT_RE),
        ("id", ID_RE),
        ("number", NUMBER_RE),
    ):
        for match in pattern.finditer(answer):
            if overlaps(match.start(), match.end(), occupied):
                continue
            if kind == "number" and looks_like_non_claim_number(answer, match.start(), match.end()):
                continue
            raw = match.group(0).strip()
            normalized = normalize_claim_value(kind, raw)
            if normalized is None:
                continue
            occupied.append((match.start(), match.end()))
            sentence, sentence_start, _ = sentence_span_at(answer, match.start(), match.end())
            drafts.append(
                ClaimDraft(
                    kind=kind,  # type: ignore[arg-type]
                    text=sentence,
                    text_start=sentence_start,
                    start=match.start(),
                    end=match.end(),
                    raw_value=raw,
                    normalized_value=normalized,
                    unit="%" if kind == "percentage" else None,
                    anchors=anchors(window(answer, match.start(), match.end())),
                )
            )
    for sentence, start, end in sentences(answer):
        marker = CAUSAL_RE.search(sentence)
        if marker:
            cause = sentence[marker.end() :].strip(" :,-.")
            if cause:
                drafts.append(
                    ClaimDraft(
                        kind="causal",
                        text=sentence,
                        text_start=start,
                        start=start,
                        end=end,
                        raw_value=cause,
                        normalized_value=normalize_text(cause),
                        unit=None,
                        anchors=anchors(sentence[: marker.start()]),
                    )
                )
        if SCOPE_RE.search(sentence) or SCREEN_ABSENCE_RE.search(sentence):
            drafts.append(
                ClaimDraft(
                    kind="scope",
                    text=sentence,
                    text_start=start,
                    start=start,
                    end=end,
                    raw_value=sentence,
                    normalized_value=normalize_text(sentence),
                    unit=None,
                    anchors=anchors(sentence),
                )
            )
    drafts.sort(key=lambda claim: (claim.start, claim.end, claim.kind))
    overflow = len(drafts) > MAX_CLAIMS
    return tuple(drafts[:MAX_CLAIMS]), overflow


def window(text: str, start: int, end: int, radius: int = 48) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def sentence_at(text: str, start: int, end: int) -> str:
    return sentence_span_at(text, start, end)[0]


def sentence_span_at(text: str, start: int, end: int) -> tuple[str, int, int]:
    for sentence, sentence_start, sentence_end in sentences(text):
        if sentence_start <= start and end <= sentence_end:
            return sentence, sentence_start, sentence_end
    return text[start:end], start, end


def sentences(text: str) -> tuple[tuple[str, int, int], ...]:
    out: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[^\n.!?]+(?:[.!?]+|$)", text):
        raw = match.group(0)
        sentence = raw.strip()
        if sentence:
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            out.append((sentence, match.start() + leading, match.end() - trailing))
    return tuple(out)


def looks_like_non_claim_number(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 2) : start]
    after = text[end : min(len(text), end + 1)]
    token = text[start:end]
    return bool(
        re.search(r"[TtVv]$", before)
        or (start == 0 or text[start - 1] == "\n")
        and after in {".", ")"}
        or len(token) == 1
        and token in {"0", "1", "2"}
        and before.lower().endswith("t")
    )
