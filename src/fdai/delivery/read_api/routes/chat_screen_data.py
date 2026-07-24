"""Deterministic Bragi T0 answers for current-screen data questions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_KEY_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\beps\b", re.I), ("eps",)),
    (re.compile(r"\battention\b|주의", re.I), ("attention.total", "attention_total")),
    (re.compile(r"\bt0\b", re.I), ("tier.t0", "t0_share")),
    (re.compile(r"\bt1\b", re.I), ("tier.t1", "t1_share")),
    (re.compile(r"\bt2\b", re.I), ("tier.t2", "t2_share")),
    (re.compile(r"\bshadow\b|관찰", re.I), ("shadow_share",)),
    (re.compile(r"\bobject\s*types?\b", re.I), ("object_type_count",)),
    (re.compile(r"\blink\s*types?\b|リンクタイプ", re.I), ("link_type_count",)),
    (re.compile(r"\baffected\b|영향", re.I), ("affected_count",)),
    (re.compile(r"\bterminal\s+stage\b|최종\s*단계", re.I), ("terminal_stage",)),
)

_ABSENT_TOPICS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (re.compile(r"\bcpu\b", re.I), "CPU usage", "CPU 사용률", "CPU 使用率"),
    (re.compile(r"\bmonthly cost\b|월\s*비용", re.I), "monthly cost", "월 비용", "月額コスト"),
    (re.compile(r"\bregion\b|리전", re.I), "Azure region", "Azure 리전", "Azure リージョン"),
    (re.compile(r"\bowner\b|소유자", re.I), "resource owner", "리소스 소유자", "リソース所有者"),
    (re.compile(r"\bwho approved\b|누가\s*승인", re.I), "approver", "승인자", "承認者"),
)


def render_screen_data_answer(
    prompt: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    """Render one bounded screen answer, or ``None`` when T0 has no target."""

    if not isinstance(view_context.get("_screen_scope"), Mapping):
        return None
    facts = _facts(view_context)
    for pattern, keys in _KEY_PATTERNS:
        if not pattern.search(prompt):
            continue
        match = next((facts[key] for key in keys if key in facts), None)
        if match is not None:
            key, value = match
            return _fact_answer(key, value, locale=locale)
        return _absence_answer(_topic(pattern, prompt), locale=locale)

    for answer in (
        _audit_answer(prompt, view_context, locale=locale),
        _top_action_answer(prompt, view_context, locale=locale),
        _promotion_answer(prompt, view_context, locale=locale),
        _failed_answer(prompt, view_context, locale=locale),
    ):
        if answer is not None:
            return answer

    for pattern, english, korean, japanese in _ABSENT_TOPICS:
        if pattern.search(prompt):
            return _absence_answer(
                _localized(english, korean, japanese, locale=locale),
                locale=locale,
            )
    return None


def _facts(view_context: Mapping[str, Any]) -> dict[str, tuple[str, Any]]:
    result: dict[str, tuple[str, Any]] = {}
    raw = view_context.get("facts")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return result
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        if isinstance(key, str) and key:
            result[key.casefold()] = (key, item.get("value"))
    return result


def _rows(view_context: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    records = view_context.get("records")
    if not isinstance(records, Mapping):
        return []
    value = records.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _audit_answer(
    prompt: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if not re.search(r"\b(?:latest|recent)\b|최근", prompt, re.I):
        return None
    rows = _rows(view_context, "items")
    if not rows:
        return None
    latest = max(
        rows,
        key=lambda row: (str(row.get("recorded_at") or ""), int(row.get("seq") or 0)),
    )
    if re.search(r"\b(?:who|actor|logged)\b|누가", prompt, re.I):
        actor = latest.get("actor")
        return _fact_answer("actor", actor, locale=locale) if actor is not None else None
    if re.search(r"\bmode\b|모드", prompt, re.I):
        mode = latest.get("mode")
        return _fact_answer("mode", mode, locale=locale) if mode is not None else None
    return None


def _top_action_answer(
    prompt: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if not re.search(r"\b(?:top|most common|common action)\b|가장\s*흔한\s*액션", prompt, re.I):
        return None
    rows = _rows(view_context, "by_action_kind")
    if not rows:
        return None
    top = max(rows, key=lambda row: int(row.get("count") or 0))
    action = top.get("key")
    count = top.get("count")
    if action is None:
        return None
    if _primary_locale(locale) == "ko":
        return f"가장 흔한 액션은 `{action}`이며 {count}건입니다."
    return f"The most common action is `{action}` with {count} records."


def _promotion_answer(
    prompt: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    rows = _rows(view_context, "rows")
    if not rows or not re.search(r"\b(?:promot|ready)\w*\b|준비|승격", prompt, re.I):
        return None
    lowered = prompt.casefold()
    selected = next(
        (
            row
            for row in rows
            if _action_type_mentioned(str(row.get("action_type_name") or ""), lowered)
        ),
        None,
    )
    if selected is not None:
        name = selected.get("action_type_name")
        gaps = selected.get("gaps")
        rendered_gaps = ", ".join(str(item) for item in gaps) if isinstance(gaps, list) else ""
        if _primary_locale(locale) == "ko":
            return f"`{name}`은 아직 준비되지 않았습니다. 근거: {rendered_gaps}."
        return f"`{name}` is not ready. Evidence: {rendered_gaps}."
    ready = [str(row.get("action_type_name")) for row in rows if row.get("ready") is True]
    if not ready:
        return _absence_answer("ready ActionType", locale=locale)
    return _fact_answer("ready ActionType", ", ".join(ready), locale=locale)


def _failed_answer(
    prompt: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if not re.search(r"\bfailed\b|실패", prompt, re.I):
        return None
    headline = view_context.get("headline")
    if not isinstance(headline, str):
        return None
    match = re.search(r"(\d+)\s+failed\b", headline, re.I)
    return _fact_answer("failed", match.group(1), locale=locale) if match else None


def _fact_answer(key: str, value: Any, *, locale: str | None) -> str:
    primary = _primary_locale(locale)
    if primary == "ko":
        return f"현재 화면의 {key}: {value}."
    if primary == "ja":
        return f"現在の画面の {key}: {value}."
    return f"The current screen shows {key}: {value}."


def _absence_answer(topic: str, *, locale: str | None) -> str:
    primary = _primary_locale(locale)
    if primary == "ko":
        return f"현재 화면에는 {topic} 정보가 없습니다."
    if primary == "ja":
        return f"現在の画面には {topic} の情報がありません。"
    return f"The current screen does not show {topic}."


def _topic(pattern: re.Pattern[str], prompt: str) -> str:
    match = pattern.search(prompt)
    return match.group(0) if match is not None else "the requested field"


def _localized(english: str, korean: str, japanese: str, *, locale: str | None) -> str:
    return {"ko": korean, "ja": japanese}.get(_primary_locale(locale), english)


def _action_type_mentioned(action_type: str, lowered_prompt: str) -> bool:
    canonical = action_type.casefold()
    short = canonical.rsplit(".", 1)[-1]
    return bool(canonical and (canonical in lowered_prompt or short in lowered_prompt))


def _primary_locale(locale: str | None) -> str:
    return (locale or "en").casefold().split("-", 1)[0].split("_", 1)[0]


__all__ = ["render_screen_data_answer"]
