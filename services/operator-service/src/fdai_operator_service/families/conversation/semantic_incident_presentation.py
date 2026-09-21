"""Render bounded read-only Incident presentation blocks from verified evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject

_MAX_INCIDENT_TABLE_ROWS = 40
_INCIDENT_TIMELINE_ROWS = 10
_INCIDENT_PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("title", "제목", "Title"),
    ("severity", "심각도", "Severity"),
    ("status", "상태", "Status"),
    ("vertical", "버티컬", "Vertical"),
    ("opened_at", "최초 기록", "First recorded"),
    ("last_updated_at", "최종 기록", "Last recorded"),
    ("actors", "관여 주체", "Actors"),
)
_INCIDENT_GAP_NEXT_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "incident_profile_missing",
        "이 상관관계에 인시던트 레코드가 존재하는지 확인하세요.",
        "Confirm an incident record exists for this correlation.",
    ),
    (
        "root_cause_missing",
        "근거 인용이 포함된 RCA 가설이 기록되었는지 확인하세요.",
        "Confirm that an RCA hypothesis with grounded citations has been recorded.",
    ),
    (
        "impact_evidence_missing",
        "영향받은 리소스의 영향 근거를 수집하세요.",
        "Collect impact evidence for the affected resources.",
    ),
    (
        "grounded_citations_missing",
        "각 주장을 감사 기록에 연결하는 근거 인용을 수집하세요.",
        "Collect grounded citations that link each claim to an audit record.",
    ),
    (
        "correlated_audit_truncated",
        "더 높은 레코드 한도로 이 조회를 다시 실행하세요.",
        "Re-run this query with a higher record limit.",
    ),
)


def readable_gap(gap: str, *, korean: bool) -> str:
    """Render one gap key without exposing Markdown-significant underscores."""
    readable = gap.replace("_", " ").strip() or gap
    return f"근거 공백: {readable}" if korean else f"Evidence gap: {readable}"


def incident_cell(value: object) -> str | None:
    """Render one incident cell without inventing a value for a missing field."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        parts = [item for item in (incident_cell(entry) for entry in value) if item]
        return ", ".join(parts) or None
    return None


def incident_profile_items(profile: Mapping[str, object], *, korean: bool) -> list[JsonObject]:
    """Render populated profile fields plus an explicit missing status."""
    items: list[JsonObject] = []
    for key, korean_label, english_label in _INCIDENT_PROFILE_FIELDS:
        rendered = incident_cell(profile.get(key))
        if rendered is None:
            continue
        items.append(
            cast(
                JsonObject,
                {
                    "label": korean_label if korean else english_label,
                    "value": rendered,
                    "tone": "attention" if key in ("severity", "status") else "neutral",
                },
            )
        )
    if incident_cell(profile.get("status")) is None:
        items.append(
            cast(
                JsonObject,
                {
                    "label": "인시던트 상태" if korean else "Incident status",
                    "value": "미기록" if korean else "not recorded",
                    "tone": "attention",
                },
            )
        )
    return items


def incident_timeline_block(
    correlated: list[object],
    *,
    verified_records: int,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """Render the latest bounded correlated audit activity."""
    rows: list[JsonObject] = []
    for entry in correlated[-_INCIDENT_TIMELINE_ROWS:]:
        if not isinstance(entry, Mapping):
            continue
        recorded_at = incident_cell(entry.get("recorded_at"))
        audit_ref = incident_cell(entry.get("audit_ref"))
        if recorded_at is None or audit_ref is None:
            continue
        rows.append(
            cast(
                JsonObject,
                {
                    "recorded_at": recorded_at,
                    "actor": incident_cell(entry.get("actor")) or "-",
                    "action_kind": incident_cell(entry.get("action_kind")) or "-",
                    "mode": incident_cell(entry.get("mode")) or "-",
                    "audit_ref": audit_ref,
                },
            )
        )
    if not rows:
        return None
    shown, total = len(rows), max(verified_records, len(correlated))
    title = "기록된 활동" if korean else "Recorded activity"
    if total > shown:
        title += f" (최근 {shown}/{total}건)" if korean else f" (latest {shown} of {total})"
    return cast(
        JsonObject,
        {
            "slot_id": "records",
            "kind": "table",
            "title": title,
            "emphasis": "secondary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "recorded_at", "label": "기록 시각" if korean else "Recorded"},
                    {"key": "actor", "label": "주체" if korean else "Actor"},
                    {"key": "action_kind", "label": "활동" if korean else "Activity"},
                    {"key": "mode", "label": "모드" if korean else "Mode"},
                    {"key": "audit_ref", "label": "감사 참조" if korean else "Audit ref"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def incident_root_cause_block(
    root_cause: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """Render one grounded root-cause summary when populated."""
    if not isinstance(root_cause, Mapping):
        return None
    fields = (
        ("cause", "원인", "Cause"),
        ("tier", "티어", "Tier"),
        ("confidence", "신뢰도", "Confidence"),
        ("reason", "근거", "Reason"),
        ("recorded_at", "기록 시각", "Recorded"),
    )
    items = [
        cast(
            JsonObject,
            {
                "label": korean_label if korean else english_label,
                "value": rendered,
                "tone": "neutral",
            },
        )
        for key, korean_label, english_label in fields
        if (rendered := incident_cell(root_cause.get(key))) is not None
    ]
    if not items:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "root_cause",
            "kind": "summary",
            "title": "근본 원인" if korean else "Root cause",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {"items": items},
        },
    )


def incident_impact_block(
    impacts: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """Render bounded metric evidence for affected resources."""
    if not isinstance(impacts, list) or not impacts:
        return None
    rows: list[JsonObject] = []
    for impact in impacts[:_MAX_INCIDENT_TABLE_ROWS]:
        if not isinstance(impact, Mapping):
            continue
        unit = incident_cell(impact.get("unit"))
        rows.append(
            cast(
                JsonObject,
                {
                    "metric": incident_cell(impact.get("metric")) or "-",
                    "baseline": _incident_measure(impact.get("baseline"), unit),
                    "observed": _incident_measure(impact.get("observed"), unit),
                    "threshold": _incident_measure(impact.get("threshold"), unit),
                    "impact": incident_cell(impact.get("impact")) or "-",
                    "evidence_ref": incident_cell(impact.get("evidence_ref")) or "-",
                },
            )
        )
    if not rows:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "impact",
            "kind": "table",
            "title": "영향 근거" if korean else "Impact evidence",
            "emphasis": "secondary",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "metric", "label": "메트릭" if korean else "Metric"},
                    {"key": "baseline", "label": "기준" if korean else "Baseline"},
                    {"key": "observed", "label": "관측" if korean else "Observed"},
                    {"key": "threshold", "label": "임계값" if korean else "Threshold"},
                    {"key": "impact", "label": "영향" if korean else "Impact"},
                    {"key": "evidence_ref", "label": "근거" if korean else "Evidence"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def _incident_measure(value: object, unit: str | None) -> str:
    rendered = incident_cell(value)
    if rendered is None:
        return "-"
    return f"{rendered} {unit}" if unit else rendered


def incident_citations_block(
    citations: object,
    *,
    bounded_refs: list[str],
    korean: bool,
) -> JsonObject | None:
    """Render bounded grounded citations."""
    if not isinstance(citations, list) or not citations:
        return None
    rows: list[JsonObject] = []
    for citation in citations[:_MAX_INCIDENT_TABLE_ROWS]:
        if not isinstance(citation, Mapping):
            continue
        rows.append(
            cast(
                JsonObject,
                {
                    "tier": incident_cell(citation.get("tier")) or "-",
                    "kind": incident_cell(citation.get("kind")) or "-",
                    "ref": incident_cell(citation.get("ref")) or "-",
                    "summary": incident_cell(citation.get("summary")) or "-",
                    "recorded_at": incident_cell(citation.get("recorded_at")) or "-",
                },
            )
        )
    if not rows:
        return None
    return cast(
        JsonObject,
        {
            "slot_id": "citations",
            "kind": "table",
            "title": "근거 인용" if korean else "Grounded citations",
            "emphasis": "supporting",
            "collapsed": False,
            "evidence_refs": bounded_refs,
            "data": {
                "columns": [
                    {"key": "tier", "label": "티어" if korean else "Tier"},
                    {"key": "kind", "label": "종류" if korean else "Kind"},
                    {"key": "ref", "label": "참조" if korean else "Reference"},
                    {"key": "summary", "label": "요약" if korean else "Summary"},
                    {"key": "recorded_at", "label": "기록 시각" if korean else "Recorded"},
                ],
                "rows": rows,
                "status_key": None,
            },
        },
    )


def incident_next_step_rows(
    gaps: list[object],
    *,
    korean: bool,
    root_cause: object,
) -> list[JsonObject]:
    """Render the read-only steps required by measured Incident evidence gaps."""
    present = {gap for gap in gaps if isinstance(gap, str)}
    authority = "읽기 전용" if korean else "Read-only"
    rows = [
        cast(
            JsonObject,
            {"action": korean_step if korean else english_step, "authority": authority},
        )
        for key, korean_step, english_step in _INCIDENT_GAP_NEXT_STEPS
        if key in present
    ]
    if rows:
        return rows
    if (
        isinstance(root_cause, Mapping)
        and root_cause.get("next_safe_step") == "configure_notification_route"
    ):
        return [
            cast(
                JsonObject,
                {
                    "action": (
                        "notification registry에 운영 알림 채널을 하나 이상 구성한 뒤 전달을 "
                        "다시 시도하세요."
                        if korean
                        else (
                            "Configure at least one operational-alert channel in the notification "
                            "registry, then retry delivery."
                        )
                    ),
                    "authority": authority,
                },
            )
        ]
    return [
        cast(
            JsonObject,
            {
                "action": (
                    "상관된 감사 근거가 완전합니다. 기록된 활동을 검토하세요."
                    if korean
                    else "The correlated audit evidence is complete. Review the recorded activity."
                ),
                "authority": authority,
            },
        )
    ]
