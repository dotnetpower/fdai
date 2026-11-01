"""Summarize and order a Resource Health table so an answer leads with what needs attention.

The display bound keeps only the first rows of a large table, so an alphabetical cut can show
twenty healthy resources while the one that is down stays hidden. Ordering puts non-healthy
rows first, and the summary counts every row of the complete table, never only the shown ones.
A resource with no health record or an unresolved target is counted as such, never as healthy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.ontology_platform.query_values import QueryRow

_AVAILABILITY_RANK = {"unavailable": 0, "degraded": 1, "unknown": 2, "available": 4}
_NO_AVAILABILITY_RANK = 3
_OBSERVED = "observed"
_MAX_CODES = 12

_AVAILABILITY_LABELS = {
    "unavailable": ("사용 불가", "unavailable"),
    "degraded": ("성능 저하", "degraded"),
    "unknown": ("알 수 없음", "unknown"),
    "available": ("정상", "available"),
}
_COVERAGE_LABELS = {
    "no_record": ("Resource Health 기록 없음", "no Resource Health record"),
    "target_unresolved": ("조회 대상 식별 불가", "target could not be resolved"),
    "not_modeled": ("Resource Health 미지원 유형", "type not covered by Resource Health"),
    "modeling_unknown": ("지원 여부 확인 불가", "coverage could not be determined"),
    "scope_unreadable": ("범위를 읽을 수 없음", "scope unreadable"),
    "duplicate_record": ("중복 기록", "duplicate record"),
    "response_invalid": ("응답 유효하지 않음", "invalid response"),
    "response_truncated": ("응답 잘림", "truncated response"),
    "state_changed": ("조회 중 상태 변경", "state changed during the read"),
    "state_absent": ("상태 없음", "no state"),
}


def _is_health_row(values: Mapping[str, Any]) -> bool:
    return values.get("evidence_family") == "resource_health"


def health_sort_key(row: QueryRow) -> tuple[int, int, str]:
    """Order non-healthy first, then unverifiable, then healthy, each by name."""

    values = row.values
    availability = values.get("availability_state")
    rank = (
        _AVAILABILITY_RANK.get(availability, _NO_AVAILABILITY_RANK)
        if isinstance(availability, str)
        else _NO_AVAILABILITY_RANK
    )
    coverage = 0 if values.get("coverage_state") in (None, _OBSERVED) else 1
    name = values.get("name")
    if not isinstance(name, str) or not name.strip():
        props = values.get("properties")
        name = props.get("name") if isinstance(props, Mapping) else None
    return rank, coverage, name.strip().casefold() if isinstance(name, str) else ""


def order_health_rows(rows: Sequence[QueryRow]) -> list[QueryRow]:
    """Return the rows with the ones that need attention first; other rows keep their order."""

    if not any(_is_health_row(row.values) for row in rows):
        return list(rows)
    return sorted(rows, key=health_sort_key)


def summarize_health_rows(rows: Sequence[QueryRow]) -> dict[str, object] | None:
    """Count availability and coverage over every Resource Health row, or return ``None``."""

    availability: dict[str, int] = {}
    coverage: dict[str, int] = {}
    total = 0
    for row in rows:
        values = row.values
        if not _is_health_row(values):
            continue
        total += 1
        state = values.get("availability_state")
        if isinstance(state, str) and state:
            availability[state] = availability.get(state, 0) + 1
        status = values.get("coverage_state")
        if isinstance(status, str) and status and status != _OBSERVED:
            coverage[status] = coverage.get(status, 0) + 1
    if total == 0:
        return None
    return {
        "total": total,
        "availability": dict(sorted(availability.items())[:_MAX_CODES]),
        "coverage_gaps": dict(sorted(coverage.items())[:_MAX_CODES]),
    }


def health_summary_lines(summary: object, *, korean: bool) -> list[str]:
    """Return bounded markdown bullets for one validated health summary, or nothing."""

    if not isinstance(summary, Mapping):
        return []
    total = summary.get("total")
    availability = summary.get("availability")
    gaps = summary.get("coverage_gaps")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total <= 0
        or not isinstance(availability, Mapping)
        or not isinstance(gaps, Mapping)
    ):
        return []
    index = 0 if korean else 1

    def label(table: Mapping[str, tuple[str, str]], key: object) -> str:
        text = table.get(key) if isinstance(key, str) else None
        return text[index] if text is not None else "-"

    states = [
        f"{label(_AVAILABILITY_LABELS, key)} {count}"
        for key in ("unavailable", "degraded", "unknown", "available")
        if isinstance((count := availability.get(key)), int)
        and not isinstance(count, bool)
        and count > 0
    ]
    gap_parts = [
        f"{label(_COVERAGE_LABELS, key)} {count}"
        for key, count in gaps.items()
        if key in _COVERAGE_LABELS
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
    ]
    lines = [
        f"- 확인 대상 {total}개 중 {', '.join(states) if states else '상태 정보 없음'}."
        if korean
        else f"- Of {total} resources checked: {', '.join(states) if states else 'no state'}."
    ]
    if gap_parts:
        lines.append(
            f"- 상태를 확인하지 못한 리소스는 정상으로 세지 않았습니다: {', '.join(gap_parts)}."
            if korean
            else f"- Resources whose health could not be confirmed are not counted healthy: "
            f"{', '.join(gap_parts)}."
        )
    return lines


__all__ = [
    "health_sort_key",
    "health_summary_lines",
    "order_health_rows",
    "summarize_health_rows",
]
