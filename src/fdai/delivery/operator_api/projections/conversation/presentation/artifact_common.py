"""Shared bounds and block constructors for chat presentation artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.delivery.operator_api.projections.conversation.presentation.contract import (
    PresentationPlacement,
)

MAX_ARTIFACT_REFS: Final = 8
MAX_TABLE_ROWS: Final = 40
MAX_TEXT_CHARS: Final = 512


def block(
    placement: PresentationPlacement,
    *,
    kind: str,
    title: str,
    refs: tuple[str, ...],
    data: Mapping[str, object],
) -> dict[str, object]:
    return {
        "slot_id": placement.slot_id,
        "kind": kind,
        "title": title,
        "emphasis": placement.emphasis,
        "collapsed": placement.collapsed,
        "evidence_refs": list(refs),
        "data": dict(data),
    }


def summary_item(label: str, value: int, tone: str) -> dict[str, object]:
    return {"label": label, "value": str(value), "tone": tone}


def chart_item(label: str, value: int, tone: str) -> dict[str, object]:
    return {"label": label, "value": value, "tone": tone}


def mapping_rows(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def bounded_refs(values: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for value in values:
        if not value or len(value) > 1024 or value in refs:
            continue
        refs.append(value)
        if len(refs) == MAX_ARTIFACT_REFS:
            break
    return tuple(refs)


def nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def nonnegative_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def number_text(value: object) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return "unknown"


def text(value: object) -> str:
    return str(value)[:MAX_TEXT_CHARS]


def verification_label(status: str, *, korean: bool) -> str:
    if not korean:
        return {
            "verified": "Verified",
            "consistent": "Consistent",
            "corrected": "Corrected",
            "unverified": "Unverified",
        }.get(status, "Unknown")
    return {
        "verified": "검증됨",
        "consistent": "근거와 일치",
        "corrected": "수정 후 검증됨",
        "unverified": "검증 미완료",
    }.get(status, "알 수 없음")
