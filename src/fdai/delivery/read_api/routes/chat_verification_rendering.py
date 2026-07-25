"""Bounded incident and agent-activity rendering for chat verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_KOREAN_TOPIC_LABELS = {
    "memory": "메모리",
    "cpu": "CPU",
    "latency": "지연",
    "network": "네트워크",
    "database": "데이터베이스",
    "storage": "스토리지",
    "deployment": "배포",
    "quota": "할당량",
    "cost": "비용",
}


def incident_summary_line(incident: Mapping[str, Any], *, korean: bool) -> str:
    correlation = text(incident.get("correlation_id"), "unknown")
    title = text(incident.get("title"), "untitled incident")
    status = text(incident.get("status"), "unknown")
    severity = text(incident.get("severity"), "unknown")
    updated = text(incident.get("last_updated_at"), "unknown time")
    agents = strings(incident.get("involved_agents"))
    agent_text = ", ".join(agents) if agents else ("없음" if korean else "none recorded")
    if korean:
        return (
            f"- {correlation}: {title} - 상태 {status}, 심각도 {severity}, "
            f"최종 갱신 {updated}, 관여 에이전트 {agent_text}"
        )
    return (
        f"- {correlation}: {title} - status {status}, severity {severity}, "
        f"last updated {updated}, involved agents {agent_text}"
    )


def recorded_failure_lines(evidence: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    refs: list[str] = []
    failure_values = {"abstain", "deny", "error", "failed", "failure", "route_unresolved"}
    for item in mappings(evidence.get("audit_evidence")):
        action_kind = text(item.get("action_kind"), "recorded.failure")
        fields = item.get("fields")
        if not isinstance(fields, Mapping):
            continue
        reason = optional_text(fields.get("reason"))
        outcomes = {
            str(fields.get(key) or "").casefold() for key in ("decision", "outcome", "status")
        }
        failure_action = any(
            marker in action_kind.casefold()
            for marker in ("error", "escalation", "fail", "unresolved")
        )
        if reason is None or (not failure_action and outcomes.isdisjoint(failure_values)):
            continue
        lines.append(f"- {action_kind}: {reason}")
        seq = item.get("seq")
        if isinstance(seq, int) and seq >= 0:
            refs.append(f"audit:{seq}")
        if len(lines) >= 5:
            break
    return lines, refs


def agent_activity_lines(evidence: Mapping[str, Any], *, korean: bool) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in mappings(evidence.get("audit_evidence")):
        agent = optional_text(item.get("agent"))
        if agent is None or agent in seen:
            continue
        action = text(item.get("action_kind"), "recorded activity")
        recorded_at = text(item.get("recorded_at"), "unknown time")
        lines.append(
            f"- {agent}: {recorded_at}에 {action} 기록"
            if korean
            else f"- {agent}: {action} at {recorded_at}"
        )
        seen.add(agent)
        if len(lines) >= 8:
            break
    if lines:
        return lines
    selected = evidence.get("selected_incident")
    incident = selected if isinstance(selected, Mapping) else {}
    involved = incident.get("involved_agents")
    if isinstance(involved, list):
        for raw_agent in involved:
            agent = optional_text(raw_agent)
            if agent is None or agent in seen:
                continue
            lines.append(
                f"- {agent}: 참여 기록은 있으나 에이전트별 감사 활동은 기록되지 않음"
                if korean
                else f"- {agent}: involved; no agent-specific audit activity is recorded"
            )
            seen.add(agent)
            if len(lines) >= 8:
                break
    return lines


def integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def topic_text(topics: tuple[str, ...], *, korean: bool) -> str:
    if not topics:
        return "요청한 주제" if korean else "the requested topic"
    if korean:
        return ", ".join(_KOREAN_TOPIC_LABELS.get(topic, topic) for topic in topics)
    return ", ".join(topics)


def mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def text(value: Any, fallback: str) -> str:
    return optional_text(value) or fallback
