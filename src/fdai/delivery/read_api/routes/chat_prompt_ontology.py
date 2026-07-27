"""Ontology-screen prompt projection and deterministic browse answers for chat.

Split out of ``chat_prompt`` so prompt assembly keeps one responsibility and
stays inside the repository LOC guard. Behaviour is unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Final

_ONTOLOGY_PROMPT_FIELD_CHARS: Final[int] = 256


_ONTOLOGY_BROWSE_INTENT: Final = re.compile(
    r"(?=.*(?:\bontology\b|온톨로지))"
    r"(?=.*(?:\b(?:query|browse|view|inspect|access)\b|조회|탐색|보기|보여|볼|봐))",
    re.IGNORECASE | re.DOTALL,
)


def _project_ontology_browse_context(view_context: dict[str, Any]) -> dict[str, Any]:
    """Keep only ontology identity fields needed for browse/query guidance."""

    records = view_context.get("records")
    if not isinstance(records, dict):
        return view_context
    field_names: dict[str, tuple[str, ...]] = {
        "selected_object_types": ("name", "key", "description"),
        "selected_relationships": ("link", "from", "to", "cardinality", "causal"),
        "object_types": ("name",),
        "relationships": ("link", "from", "to"),
        "action_types": ("name", "category"),
    }
    projected: dict[str, Any] = {}
    for key, allowed in field_names.items():
        rows = records.get(key)
        if not isinstance(rows, list):
            continue
        projected_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            projected_row = {
                field: value
                for field in allowed
                if field in row and (value := _ontology_prompt_value(row[field])) is not None
            }
            if projected_row:
                projected_rows.append(projected_row)
        projected[key] = projected_rows
    return {
        **view_context,
        "records": projected,
        "_ontology_browse_projection": True,
    }


def _ontology_prompt_value(value: Any) -> Any | None:
    if isinstance(value, str):
        return value[:_ONTOLOGY_PROMPT_FIELD_CHARS]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return None


def _ontology_browse_answer(
    prompt: str,
    view_context: dict[str, Any],
    *,
    locale: str | None,
) -> str | None:
    """Render ontology query guidance from the current screen snapshot."""

    if str(view_context.get("routeId") or "").casefold() != "ontology":
        return None
    if not _ONTOLOGY_BROWSE_INTENT.search(prompt):
        return None
    fact_values = _unique_ontology_facts(view_context.get("facts"))
    selected = _ontology_selection(fact_values.get("selected_object_type"))
    counts = (
        ("ObjectType", _ontology_count(fact_values.get("object_type_count"))),
        ("LinkType", _ontology_count(fact_values.get("link_type_count"))),
        ("ActionType", _ontology_count(fact_values.get("action_type_count"))),
    )
    known_counts = [(label, value) for label, value in counts if value is not None]
    if locale and locale.casefold().startswith("ko"):
        count_text = (
            "현재 snapshot에서 "
            + ", ".join(f"{label} {value}개" for label, value in known_counts)
            + "가 확인됩니다."
            if known_counts
            else "현재 snapshot에서 type count를 확인할 수 없습니다."
        )
        selection_text = (
            f"선택된 ObjectType은 {selected}입니다."
            if selected is not None
            else "현재 ObjectType 선택은 unavailable 또는 ambiguous 상태입니다."
        )
        return " ".join(
            (
                "온톨로지 화면에서 객체, 링크, 작업 탭을 선택해 데이터를 조회할 수 있습니다.",
                count_text,
                selection_text,
                "객체를 선택하면 직접 연결 관계와 속성을 확인할 수 있습니다.",
                "이 화면은 읽기 전용입니다.",
            )
        )
    count_text = (
        "The current snapshot shows "
        + ", ".join(f"{value} {label}{'' if value == 1 else 's'}" for label, value in known_counts)
        + "."
        if known_counts
        else "Current type counts are unavailable in this snapshot."
    )
    selection_text = (
        f"The selected ObjectType is {selected}."
        if selected is not None
        else "The current ObjectType selection is unavailable or ambiguous."
    )
    return " ".join(
        (
            "Use the Objects, Links, and Actions tabs to inspect ontology data.",
            count_text,
            selection_text,
            "Select an object to inspect its one-hop relationships and properties.",
            "This screen is read-only.",
        )
    )


def _unique_ontology_facts(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, list):
        return {}
    recognized = {
        "selected_object_type",
        "object_type_count",
        "link_type_count",
        "action_type_count",
    }
    values: dict[str, list[Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if isinstance(key, str) and key in recognized:
            values.setdefault(key, []).append(item.get("value"))
    return {key: items[0] for key, items in values.items() if len(items) == 1}


def _ontology_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 1_000_000 else None


def _ontology_selection(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    selected = value.strip()
    if not selected or len(selected) > 128:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in selected):
        return None
    return selected
