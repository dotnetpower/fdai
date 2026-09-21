"""Project bounded Incident evidence into presentation-ready facts and actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

INCIDENT_TIMELINE_ROW_LIMIT = 10

_INCIDENT_GAP_NEXT_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "incident_profile_missing",
        "이 상관관계에 인시던트 레코드가 존재하는지 확인하세요",
        "confirm an incident record exists for this correlation",
    ),
    (
        "root_cause_missing",
        "근거 인용이 포함된 RCA 가설이 기록되었는지 확인하세요",
        "confirm that an RCA hypothesis with grounded citations has been recorded",
    ),
    (
        "impact_evidence_missing",
        "영향받은 리소스의 영향 근거를 수집하세요",
        "collect impact evidence for the affected resources",
    ),
    (
        "grounded_citations_missing",
        "각 주장을 감사 기록에 연결하는 근거 인용을 수집하세요",
        "collect grounded citations that link each claim to an audit record",
    ),
    (
        "correlated_audit_truncated",
        "더 높은 레코드 한도로 이 조회를 다시 실행하세요",
        "re-run this query with a higher record limit",
    ),
)

_INCIDENT_PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("title", "제목", "Title"),
    ("severity", "심각도", "Severity"),
    ("status", "상태", "Status"),
    ("vertical", "버티컬", "Vertical"),
    ("opened_at", "최초 기록", "First recorded"),
    ("last_updated_at", "최종 기록", "Last recorded"),
    ("actors", "관여 주체", "Actors"),
)


def incident_scalar(value: object) -> str | None:
    """Render one Incident evidence cell without inventing missing values."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        parts = [item for item in (incident_scalar(entry) for entry in value) if item]
        return ", ".join(parts) or None
    return None


def incident_next_step_actions(
    gaps: Sequence[str],
    *,
    korean: bool,
) -> tuple[str, ...]:
    """Derive concrete read-only steps from the gaps this answer actually found."""
    present = set(gaps)
    return tuple(
        korean_step if korean else english_step
        for key, korean_step, english_step in _INCIDENT_GAP_NEXT_STEPS
        if key in present
    )


def incident_profile_facts(
    profile: object,
    *,
    korean: bool,
) -> tuple[tuple[str, str], ...]:
    """Surface every populated profile field the audit projection already carries."""
    if not isinstance(profile, Mapping):
        return ()
    facts: list[tuple[str, str]] = []
    for key, korean_label, english_label in _INCIDENT_PROFILE_FIELDS:
        rendered = incident_scalar(profile.get(key))
        if rendered is not None:
            facts.append((korean_label if korean else english_label, rendered))
    return tuple(facts)


def incident_timeline_rows(evidence: object) -> tuple[Mapping[str, str], ...]:
    """Return the most recent bounded audit records in ascending recorded order."""
    if not isinstance(evidence, list):
        return ()
    rows: list[Mapping[str, str]] = []
    for entry in evidence[-INCIDENT_TIMELINE_ROW_LIMIT:]:
        if not isinstance(entry, Mapping):
            continue
        recorded_at = incident_scalar(entry.get("recorded_at"))
        audit_ref = incident_scalar(entry.get("audit_ref"))
        if recorded_at is None or audit_ref is None:
            continue
        rows.append(
            {
                "recorded_at": recorded_at,
                "actor": incident_scalar(entry.get("actor")) or "-",
                "action_kind": incident_scalar(entry.get("action_kind")) or "-",
                "mode": incident_scalar(entry.get("mode")) or "-",
                "audit_ref": audit_ref,
            }
        )
    return tuple(rows)
