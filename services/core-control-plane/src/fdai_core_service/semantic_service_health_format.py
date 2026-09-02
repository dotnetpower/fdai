"""Format validated subscription Service Health conclusions."""

from __future__ import annotations

from collections.abc import Mapping

EVENT_TYPES = ("service_issue", "health_advisory", "planned_maintenance")


def invalid_answer(korean: bool) -> str:
    if korean:
        return (
            "## Service Health 근거를 확인할 수 없음\n\n"
            "- 이벤트 요약, 유형, 개수 또는 관측 시각이 검증 계약과 일치하지 않습니다.\n"
            "- 장애 여부를 추정하지 않습니다.\n\n"
            "이 결과는 읽기 전용이며 `execution_authority=false`입니다."
        )
    return (
        "## Service Health evidence unavailable\n\n"
        "- The event summary, categories, counts, or observation time do not match the "
        "verified contract.\n"
        "- No outage status is inferred.\n\n"
        "This result is read-only and has `execution_authority=false`."
    )


def heading(
    conclusion: str,
    *,
    event_label: str,
    filtered: bool,
    korean: bool,
) -> str:
    if filtered:
        if korean:
            return {
                "yes": f"## 예 - 현재 활성 {event_label}가 있습니다",
                "no": f"## 아니요 - 현재 활성 {event_label}가 없습니다",
                "yes_partial": f"## 예 - 활성 {event_label}가 확인됐지만 전체 범위는 불완전합니다",
                "unknown": f"## 확인 불가 - 현재 활성 {event_label} 여부를 결정할 수 없습니다",
            }[conclusion]
        return {
            "yes": f"## Yes - active {event_label} are present",
            "no": f"## No - no active {event_label} are present",
            "yes_partial": (
                f"## Yes - active {event_label} were observed, but coverage is incomplete"
            ),
            "unknown": f"## Unknown - active {event_label} status cannot be determined",
        }[conclusion]
    if korean:
        return {
            "yes": "## 예 - 현재 활성 Azure Service Health 장애가 있습니다",
            "no": "## 아니요 - 현재 활성 Azure Service Health 장애가 없습니다",
            "yes_partial": "## 예 - 활성 장애가 확인됐지만 이벤트 유형 범위는 불완전합니다",
            "unknown": (
                "## 확인 불가 - 현재 활성 Azure Service Health 장애 여부를 결정할 수 없습니다"
            ),
        }[conclusion]
    return {
        "yes": "## Yes - active Azure Service Health service issues are present",
        "no": "## No - no active Azure Service Health service issues are present",
        "yes_partial": (
            "## Yes - active service issues were observed, but event-type coverage is incomplete"
        ),
        "unknown": (
            "## Unknown - active Azure Service Health service-issue status cannot be determined"
        ),
    }[conclusion]


def count_line(count: int, *, posture: object, label: str, korean: bool) -> str:
    if korean:
        if posture == "exact":
            return f"- 고유 활성 {label}: {count}건"
        if posture == "minimum":
            return f"- 확인된 최소 활성 {label}: {count}건"
        return f"- 고유 활성 {label}: 확인 불가"
    if posture == "exact":
        return f"- Unique active {label}: {count}"
    if posture == "minimum":
        return f"- Minimum observed active {label}: {count}"
    return f"- Unique active {label}: unknown"


def impacted_line(count: object, *, posture: object, korean: bool) -> str:
    if korean:
        if isinstance(count, int) and posture == "exact":
            return f"- 고유 영향 리소스: {count}개"
        if isinstance(count, int):
            return f"- 확인된 최소 영향 리소스: {count}개"
        return "- 고유 영향 리소스: 확인 불가"
    if isinstance(count, int) and posture == "exact":
        return f"- Unique impacted resources: {count}"
    if isinstance(count, int):
        return f"- Minimum observed impacted resources: {count}"
    return "- Unique impacted resources: unknown"


def category_lines(
    counts: Mapping[str, int],
    *,
    exact: bool,
    korean: bool,
) -> list[str]:
    if korean:
        labels = {
            "service_issue": "활성 장애",
            "health_advisory": "활성 상태 권고",
            "planned_maintenance": "활성 예정 유지 관리",
        }
        qualifier = "" if exact else "확인된 최소 "
        return [
            f"- {qualifier}{labels[event_type]}: {counts[event_type]}건"
            for event_type in EVENT_TYPES
        ]
    labels = {
        "service_issue": "service issues/outages",
        "health_advisory": "health advisories",
        "planned_maintenance": "planned maintenance",
    }
    qualifier = "Active" if exact else "Minimum observed active"
    return [
        f"- {qualifier} {labels[event_type]}: {counts[event_type]}" for event_type in EVENT_TYPES
    ]


def event_line(event: Mapping[str, object], *, korean: bool) -> str:
    if korean:
        return (
            "- "
            f"{event.get('impact_start_at') or '시작 시각 미확인'} - "
            f"{event.get('event_type') or '유형 미확인'} / "
            f"{event.get('status') or '상태 미확인'} / "
            f"{event.get('level') or '수준 미확인'}: "
            f"{event.get('title') or '제목 미확인'}"
        )
    return (
        "- "
        f"{event.get('impact_start_at') or 'start time unavailable'} - "
        f"{event.get('event_type') or 'type unavailable'} / "
        f"{event.get('status') or 'status unavailable'} / "
        f"{event.get('level') or 'level unavailable'}: "
        f"{event.get('title') or 'title unavailable'}"
    )


def event_label(measure_concepts: tuple[str, ...], *, korean: bool) -> str:
    selected = set(measure_concepts) - {"service_health.active_event"}
    labels = {
        "service_health.service_issue": (
            "Azure Service Health 장애" if korean else "Azure Service Health service issues"
        ),
        "service_health.planned_maintenance": (
            "Azure 예정 유지 관리" if korean else "Azure planned maintenance events"
        ),
        "service_health.health_advisory": (
            "Azure 상태 권고" if korean else "Azure health advisories"
        ),
    }
    if len(selected) == 1 and (concept := next(iter(selected))) in labels:
        return labels[concept]
    if selected:
        return (
            "요청한 유형의 Azure Service Health 이벤트"
            if korean
            else "requested Azure Service Health events"
        )
    return "Azure Service Health 이벤트" if korean else "Azure Service Health events"


__all__ = [
    "EVENT_TYPES",
    "category_lines",
    "count_line",
    "event_label",
    "event_line",
    "heading",
    "impacted_line",
    "invalid_answer",
]
