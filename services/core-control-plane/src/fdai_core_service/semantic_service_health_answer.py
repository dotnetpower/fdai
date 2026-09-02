"""Render subscription Service Health without conflating event categories."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from .semantic_service_health_format import (
    EVENT_TYPES,
    category_lines,
    count_line,
    event_label,
    event_line,
    heading,
    impacted_line,
    invalid_answer,
)

_EVENT_TYPE_BY_MEASURE = {
    "service_health.service_issue": "service_issue",
    "service_health.health_advisory": "health_advisory",
    "service_health.planned_maintenance": "planned_maintenance",
}


def render_service_health_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    measure_concepts: tuple[str, ...],
) -> str | None:
    """Render outage status only from complete or positively observed service-issue rows."""

    if output_shape != "subscription_service_health":
        return None
    if len(outputs) != 1:
        return invalid_answer(korean)
    output = outputs[0]
    rows = output.get("rows")
    if not isinstance(rows, list):
        return invalid_answer(korean)
    if not rows:
        return invalid_answer(korean)
    summary_row = rows[0]
    summary = summary_row.get("values") if isinstance(summary_row, Mapping) else None
    if (
        not isinstance(summary, Mapping)
        or summary.get("record_kind") != "summary"
        or summary.get("scope_kind") != "subscription"
        or summary.get("execution_authority") is not False
    ):
        return invalid_answer(korean)
    event_count = summary.get("active_event_count")
    impacted_count = summary.get("impacted_resource_count")
    count_posture = summary.get("count_posture")
    observed_at = summary.get("observed_at")
    observed_at_time = _parse_timestamp(observed_at)
    if (
        not _optional_count(event_count)
        or not _optional_count(impacted_count)
        or count_posture not in {"exact", "minimum", "unknown"}
        or observed_at_time is None
    ):
        return invalid_answer(korean)
    returned_rows = output.get("returned_rows")
    total_rows = output.get("total_rows")
    display_truncated = output.get("display_truncated")
    if (
        not _optional_count(returned_rows)
        or not _optional_count(total_rows)
        or returned_rows != len(rows)
        or not isinstance(total_rows, int)
        or total_rows < len(rows)
        or not isinstance(display_truncated, bool)
        or display_truncated != (total_rows > len(rows))
    ):
        return invalid_answer(korean)

    events_by_id: dict[str, Mapping[str, object]] = {}
    impacted_refs: set[str] = set()
    for row in rows[1:]:
        values = row.get("values") if isinstance(row, Mapping) else None
        if (
            not isinstance(values, Mapping)
            or values.get("record_kind") != "event"
            or values.get("scope_kind") != "subscription"
            or values.get("execution_authority") is not False
            or not _bounded_string(values.get("event_id"), maximum=256)
            or not _bounded_string(values.get("event_evidence_ref"), maximum=256)
            or values.get("event_type") not in EVENT_TYPES
            or values.get("status") != "active"
        ):
            return invalid_answer(korean)
        impact_start_at = _parse_timestamp(values.get("impact_start_at"))
        event_observed_at = _parse_timestamp(values.get("observed_at"))
        if (
            impact_start_at is None
            or impact_start_at > observed_at_time
            or event_observed_at != observed_at_time
        ):
            return invalid_answer(korean)
        event_id = cast(str, values["event_id"])
        existing = events_by_id.get(event_id)
        if existing is not None and _event_identity(existing) != _event_identity(values):
            return invalid_answer(korean)
        events_by_id.setdefault(event_id, values)
        if isinstance((impacted_ref := values.get("impacted_resource_ref")), str):
            impacted_refs.add(impacted_ref)

    complete = output.get("source_complete") is True
    events = list(events_by_id.values())
    event_ids = set(events_by_id)
    if event_count is None:
        if event_ids or complete:
            return invalid_answer(korean)
        observed_event_count = 0
    else:
        observed_event_count = event_count
    if not _valid_count_posture(
        complete=complete,
        event_count=event_count,
        count_posture=count_posture,
    ):
        return invalid_answer(korean)
    if (display_truncated and len(event_ids) > observed_event_count) or (
        not display_truncated and len(event_ids) != observed_event_count
    ):
        return invalid_answer(korean)
    hidden_rows = total_rows - len(rows)
    if observed_event_count > len(event_ids) + hidden_rows:
        return invalid_answer(korean)
    if not _valid_impacted_count(
        complete=complete,
        display_truncated=display_truncated,
        impacted_count=impacted_count,
        observed_refs=len(impacted_refs),
        hidden_rows=hidden_rows,
    ):
        return invalid_answer(korean)

    filtered = bool(set(measure_concepts) - {"service_health.active_event"})
    selected_event_types = {
        _EVENT_TYPE_BY_MEASURE[measure]
        for measure in measure_concepts
        if measure in _EVENT_TYPE_BY_MEASURE
    }
    if filtered and (
        not selected_event_types
        or any(event.get("event_type") not in selected_event_types for event in events)
    ):
        return invalid_answer(korean)
    label = event_label(measure_concepts, korean=korean)
    category_complete = (
        complete
        and len(event_ids) == observed_event_count
        and all(event.get("event_type") in EVENT_TYPES for event in events)
    )
    category_counts = {
        event_type: sum(event.get("event_type") == event_type for event in events)
        for event_type in EVENT_TYPES
    }
    if filtered:
        conclusion = _event_conclusion(complete, observed_event_count)
    else:
        conclusion = _outage_conclusion(
            category_complete=category_complete,
            service_issue_count=category_counts["service_issue"],
        )

    limitation = output.get("source_truncation_reason")
    limitation_text = limitation if isinstance(limitation, str) and limitation else None
    count_label = label if filtered else ("이벤트" if korean else "events")
    lines = [
        heading(conclusion, event_label=label, filtered=filtered, korean=korean),
        "",
        "- 범위: 서버에 구성된 Azure 구독"
        if korean
        else "- Scope: the server-configured Azure subscription",
        count_line(
            observed_event_count,
            posture=count_posture,
            label=count_label,
            korean=korean,
        ),
        impacted_line(impacted_count, posture=count_posture, korean=korean),
        f"- 관측 시각: {observed_at}" if korean else f"- Observed at: {observed_at}",
        (
            f"- 원본 완전성: {'complete' if complete else 'incomplete'}"
            if korean
            else f"- Source completeness: {'complete' if complete else 'incomplete'}"
        ),
    ]
    if not filtered:
        lines.extend(
            category_lines(
                category_counts,
                exact=category_complete,
                korean=korean,
            )
        )
    if limitation_text is not None:
        lines.append(
            f"- 제한 사항: `{limitation_text}`" if korean else f"- Limitation: `{limitation_text}`"
        )

    displayed_events = events[:8]
    if events:
        lines.extend(
            [
                "",
                f"## 확인된 활성 {count_label}" if korean else f"## Observed active {count_label}",
                "",
            ]
        )
        lines.extend(event_line(event, korean=korean) for event in displayed_events)
    if len(displayed_events) < observed_event_count:
        lines.append(
            f"- 표시한 이벤트: 고유 이벤트 {observed_event_count}건 중 {len(displayed_events)}건"
            if korean
            else (
                f"- Displayed events: {len(displayed_events)} of {observed_event_count} "
                "unique events"
            )
        )
    lines.extend(
        [
            "",
            "이 결과는 읽기 전용이며 `execution_authority=false`입니다."
            if korean
            else "This result is read-only and has `execution_authority=false`.",
        ]
    )
    return "\n".join(lines)


def _optional_count(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _bounded_string(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _valid_count_posture(
    *,
    complete: bool,
    event_count: object,
    count_posture: object,
) -> bool:
    if complete:
        return event_count is not None and count_posture == "exact"
    if event_count is None:
        return count_posture == "unknown"
    return isinstance(event_count, int) and event_count > 0 and count_posture == "minimum"


def _event_identity(event: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        event.get(field)
        for field in (
            "event_type",
            "title",
            "level",
            "status",
            "impact_start_at",
            "observed_at",
            "event_evidence_ref",
        )
    )


def _valid_impacted_count(
    *,
    complete: bool,
    display_truncated: bool,
    impacted_count: object,
    observed_refs: int,
    hidden_rows: int,
) -> bool:
    if not display_truncated:
        expected = observed_refs if complete or observed_refs else None
        return impacted_count == expected
    if impacted_count is None:
        return observed_refs == 0 and not complete
    return (
        isinstance(impacted_count, int)
        and (complete or impacted_count > 0)
        and observed_refs <= impacted_count <= observed_refs + hidden_rows
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _event_conclusion(complete: bool, count: int) -> str:
    if complete:
        return "yes" if count else "no"
    return "yes_partial" if count else "unknown"


def _outage_conclusion(*, category_complete: bool, service_issue_count: int) -> str:
    if service_issue_count:
        return "yes" if category_complete else "yes_partial"
    return "no" if category_complete else "unknown"


__all__ = ["render_service_health_answer"]
