"""Render one verified property of one Resource as its exact value, never as prose.

A compiled property lookup projects the Resource's identity and one reviewed field. The
answer shows that exact value under the property's grounded identity. A missing value is
stated as unknown and never guessed or filled from another field.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

_SHAPE = "target_property_value"
_TYPE_FIELD = "properties.type"
_IDENTITY = frozenset({"id", "properties.name", _TYPE_FIELD})
_MAX_VALUE_CHARS = 400
_STRUCTURED = object()


def render_property_value_answer(
    outputs: Sequence[Mapping[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    measure_concepts: tuple[str, ...],
) -> str | None:
    """Return the property answer for one verified row, or ``None`` to defer."""

    if output_shape != _SHAPE or len(outputs) != 1 or len(measure_concepts) != 2:
        return None
    rows = outputs[0].get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    values = rows[0].get("values")
    if not isinstance(values, Mapping):
        return None
    label, field = measure_concepts
    if any(isinstance(key, str) and key not in _IDENTITY and key != field for key in values):
        return None
    # Answer rows keep scalar fields only, so a structured value is named, never replaced.
    value = values.get(field, _STRUCTURED) if field != _TYPE_FIELD else values.get(field)
    name = _text(values.get("properties.name")) or _text(values.get("id")) or "-"
    heading = f"## {name}의 {label}" if korean else f"## {label} of {name}"
    if value is _STRUCTURED:
        line = (
            f"- {label}: 구조화된 값이므로 기술 상세에서 확인할 수 있습니다."
            if korean
            else f"- {label}: a structured value, shown in technical details."
        )
    elif value is None:
        line = (
            "- 이 속성에는 기록된 값이 없어 알 수 없습니다."
            if korean
            else "- No value is recorded for this property, so it is unknown."
        )
    else:
        line = f"- {label}: {_display(value, korean=korean)}"
    kind = _text(values.get(_TYPE_FIELD))
    lines = [heading, "", line]
    if kind:
        lines.append(f"- 리소스 유형: {kind}" if korean else f"- Resource type: {kind}")
    return "\n".join(lines)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _display(value: object, *, korean: bool) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
    if len(text) > _MAX_VALUE_CHARS:
        # A long value is named, not cut, so the answer never shows a partial value.
        return "(기술 상세 참조)" if korean else "(see technical details)"
    return text.replace("\r", " ").replace("\n", " ")


__all__ = ["render_property_value_answer"]
