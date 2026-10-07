"""Show verified query output rows as a bounded evidence table, never as authored prose.

A verified result without a reviewed presentation used to show only its row count, so a
compiled count or relation read hid its answer in technical details. The table displays the
verified values exactly, states how many rows it does not show, and adds no fact of its own.
"""

from __future__ import annotations

from collections.abc import Mapping

_MAX_ROWS = 20
_MAX_COLUMNS = 6
_MAX_CELL_CHARS = 120
_MAX_TABLE_CHARS = 4_000
# Display order for common verified fields; every other field follows in first-seen order.
_LEADING_FIELDS = (
    "name",
    "root_name",
    "member_name",
    "type",
    "status",
    "location",
    "operation",
    "rank",
    "value",
    "unit",
    "group",
    "missing_reason",
)
# The identity and ObjectType of a named row stay in technical details, where they are exact.
_DETAIL_FIELDS = frozenset({"id", "object_type"})


def verified_rows_table(
    output: Mapping[str, object], *, korean: bool, leading: tuple[str, ...] = ()
) -> list[str]:
    """Return markdown table lines for one verified output, or nothing without rows.

    ``leading`` names the measure fields the frame reads, such as a reader's declared
    state fields, so the fields that answer the question show before receipt fields.
    """

    rows = output.get("rows")
    values = [
        row["values"]
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping) and isinstance(row.get("values"), Mapping)
    ]
    if not values:
        return []
    seen: dict[str, None] = {}
    for item in values:
        for key in item:
            if isinstance(key, str):
                seen.setdefault(key, None)
    named = "name" in seen
    first = ["name"] if named else []
    ordered = [*first, *(key for key in (*leading, *_LEADING_FIELDS) if key in seen)]
    ordered = list(dict.fromkeys(ordered))
    columns = ordered + [
        key for key in seen if key not in ordered and not (named and key in _DETAIL_FIELDS)
    ]
    shown_columns = columns[:_MAX_COLUMNS]
    lines = ["", "| " + " | ".join(shown_columns) + " |", "|" + "---|" * len(shown_columns)]
    budget = _MAX_TABLE_CHARS - sum(len(line) for line in lines)
    shown_rows = 0
    for item in values[:_MAX_ROWS]:
        line = "| " + " | ".join(_bounded(_cell(item.get(key)), korean) for key in shown_columns)
        line += " |"
        if len(line) > budget:
            break
        lines.append(line)
        budget -= len(line)
        shown_rows += 1
    if shown_rows == 0:
        return []
    hidden_rows = len(values) - shown_rows
    hidden_columns = len(columns) - len(shown_columns)
    if hidden_rows > 0:
        lines.append(
            f"- 표에 표시하지 않은 검증된 행 {hidden_rows}개는 기술 상세에 있습니다."
            if korean
            else f"- {hidden_rows} more verified rows are in technical details."
        )
    if hidden_columns > 0:
        lines.append(
            f"- 표에 표시하지 않은 검증된 필드 {hidden_columns}개는 기술 상세에 있습니다."
            if korean
            else f"- {hidden_columns} more verified fields are in technical details."
        )
    return lines


# Reviewed limitation notices a compiled frame requires its answer to state. They restate the
# read, never an operational fact, and each maps to one frame evidence requirement.
_WINDOW_NOTICES = {
    "applied": ("조회 기간: 질문에서 밝힌 최근 {span}", "Read window: the last {span}, as stated."),
    "default": (
        "조회 기간: 기간을 밝히지 않아 적용한 기본값인 최근 {span}",
        "Read window: no period was stated, so the default, the last {span}, was read.",
    ),
    "model_judged": (
        "조회 기간: 질문의 표현에서 판단한 최근 {span}",
        "Read window: the last {span}, as judged from the question's wording.",
    ),
    "fixed": (
        "조회 기간: 상태 이상 평가의 검토된 고정 기간인 최근 {span}",
        "Read window: the last {span}, the reviewed fixed window of the health assessment.",
    ),
}
_CAUSE_NOTICE = (
    "원인은 확정하지 않았습니다. 아래는 현재 상태와 조회 기간에 기록된 작업이며, "
    "어느 작업이 원인인지는 판단하지 않았습니다.",
    "The cause is not established. The tables show the current state and the operations "
    "recorded in the window; none of them is identified as the cause.",
)


_IMPACT_NOTICE = (
    "아래는 관측된 영향이 아니라, 의존 관계로 볼 때 영향을 받을 수 있는 리소스입니다.",
    "The rows below are resources that could be affected through their dependencies, "
    "not an observed impact.",
)


_UNIQUENESS_NOTICE = (
    "인벤토리 수집이 완료되지 않은 상태에서 이름으로 찾은 리소스입니다. 같은 이름의 다른 "
    "리소스가 아직 반영되지 않았을 수 있습니다.",
    "This resource was matched by name while the inventory was incomplete, so another "
    "resource with the same name may not be reflected yet.",
)
# A property value states where it came from and the freshness its reviewed meaning needs.
_PROPERTY_NOTICE = (
    "값 출처: 이 리소스의 인벤토리 기록입니다. 개별 속성을 관측한 시각은 기록되지 않으며, "
    "이 속성의 검토된 최신성 기준은 {span}입니다.",
    "Value source: this resource's inventory record. The time a single property was "
    "observed isn't recorded, and the reviewed freshness bound for this property is {span}.",
)
_COMPARED_NOTICE = (
    "비교한 기간: 최근 {recent}와 그 직전 {earlier}",
    "Compared windows: the last {recent}, and the {earlier} just before it.",
)
_FIXED_NOTICES = {
    "cause.not_established": _CAUSE_NOTICE,
    "impact.possible_not_observed": _IMPACT_NOTICE,
    "anchor.uniqueness_unproven": _UNIQUENESS_NOTICE,
}


def with_stated_notices(answer: str, requirements: tuple[str, ...], *, locale: str) -> str:
    """Insert the reviewed notices a compiled frame requires right after the answer heading."""

    korean = locale.casefold().startswith("ko")
    notices: list[str] = []
    for requirement in requirements:
        fixed = _FIXED_NOTICES.get(requirement)
        if fixed is not None:
            notices.append(fixed[0] if korean else fixed[1])
            continue
        compared = requirement.removeprefix("window.compared.").split(".")
        if requirement.startswith("window.compared.") and len(compared) == 2:
            if all(part.isdigit() for part in compared):
                earlier, recent = (_window_span(int(part), korean=korean) for part in compared)
                text = _COMPARED_NOTICE[0] if korean else _COMPARED_NOTICE[1]
                notices.append(text.format(earlier=earlier, recent=recent))
            continue
        bound = requirement.removeprefix("property.inventory.")
        if bound != requirement:
            if bound.isdigit():
                text = _PROPERTY_NOTICE[0] if korean else _PROPERTY_NOTICE[1]
                notices.append(text.format(span=_window_span(int(bound), korean=korean)))
            continue
        kind, _, seconds = requirement.removeprefix("window.").partition(".")
        templates = _WINDOW_NOTICES.get(kind) if requirement.startswith("window.") else None
        if templates is None or not seconds.isdigit():
            continue
        text = templates[0] if korean else templates[1]
        notices.append(text.format(span=_window_span(int(seconds), korean=korean)))
    if not notices:
        return answer
    heading, _, rest = answer.partition("\n")
    return "\n".join([heading, "", *(f"- {notice}" for notice in notices), rest])


def _window_span(seconds: int, *, korean: bool) -> str:
    for unit_seconds, korean_unit, english_unit in (
        (604_800, "주", "week"),
        (86_400, "일", "day"),
        (3_600, "시간", "hour"),
        (60, "분", "minute"),
    ):
        if seconds % unit_seconds == 0:
            count = seconds // unit_seconds
            if korean:
                return f"{count}{korean_unit}"
            return f"{count} {english_unit}{'' if count == 1 else 's'}"
    return f"{seconds}초" if korean else f"{seconds} seconds"


def _bounded(cell: str, korean: bool) -> str:
    # A long value is named, not cut, so a shown cell never displays a partial value.
    if len(cell) <= _MAX_CELL_CHARS:
        return cell
    return "(기술 상세 참조)" if korean else "(see technical details)"


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        return ", ".join(f"{key}={_scalar(item)}" for key, item in value.items()) or "-"
    if isinstance(value, list | tuple):
        return ", ".join(_scalar(item) for item in value) or "-"
    return _scalar(value)


def _scalar(value: object) -> str:
    # Fifteen significant digits drop binary float noise and keep every meaningful digit.
    text = "-" if value is None else f"{value:.15g}" if isinstance(value, float) else str(value)
    # Table syntax characters are escaped so a verified value cannot change the table shape.
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


__all__ = ["verified_rows_table"]
