"""A Resource Health answer leads with what needs attention and counts the whole table."""

from __future__ import annotations

from fdai.core.ontology_platform.query_values import QueryRow
from fdai_core_service.semantic_resource_health_summary import (
    health_summary_lines,
    order_health_rows,
    summarize_health_rows,
)


def _row(name: str, availability: str | None, coverage: str = "observed") -> QueryRow:
    values: dict[str, object] = {
        "evidence_family": "resource_health",
        "name": name,
        "coverage_state": coverage,
    }
    if availability is not None:
        values["availability_state"] = availability
    return QueryRow.from_values(f"row-{name}", values)


def _table() -> list[QueryRow]:
    return [
        _row("a-ok", "available"),
        _row("b-ok", "available"),
        _row("c-down", "unavailable"),
        _row("d-slow", "degraded"),
        _row("e-unknown", "unknown"),
        _row("f-none", None, "no_record"),
        _row("g-lost", None, "target_unresolved"),
    ]


def test_non_healthy_rows_come_first_and_unverifiable_rows_before_healthy_ones() -> None:
    ordered = [row.values["name"] for row in order_health_rows(_table())]

    assert ordered == ["c-down", "d-slow", "e-unknown", "f-none", "g-lost", "a-ok", "b-ok"]


def test_the_summary_counts_every_row_and_never_counts_a_gap_as_healthy() -> None:
    summary = summarize_health_rows(_table())

    assert summary == {
        "total": 7,
        "availability": {"available": 2, "degraded": 1, "unavailable": 1, "unknown": 1},
        "coverage_gaps": {"no_record": 1, "target_unresolved": 1},
    }


def test_the_summary_is_in_the_operators_language_and_states_the_gap_rule() -> None:
    summary = summarize_health_rows(_table())

    english = "\n".join(health_summary_lines(summary, korean=False))
    korean = "\n".join(health_summary_lines(summary, korean=True))

    assert "Of 7 resources checked: unavailable 1, degraded 1, unknown 1, available 2" in english
    assert "not counted healthy" in english and "no Resource Health record 1" in english
    assert "확인 대상 7개 중 사용 불가 1, 성능 저하 1, 알 수 없음 1, 정상 2" in korean
    assert "정상으로 세지 않았습니다" in korean


def test_other_tables_and_malformed_summaries_produce_nothing() -> None:
    other = [QueryRow.from_values("r1", {"name": "vm", "type": "compute.vm"})]

    assert [row.row_id for row in order_health_rows(other)] == ["r1"]
    assert summarize_health_rows(other) is None
    assert health_summary_lines(None, korean=False) == []
    assert health_summary_lines({"total": "7"}, korean=False) == []
