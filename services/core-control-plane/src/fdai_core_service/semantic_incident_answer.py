"""Render bounded, read-only Incident evidence answers in the operator locale."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai_service_contracts import SemanticTurnRequest

from .semantic_incident_evidence import (
    INCIDENT_TIMELINE_ROW_LIMIT,
    incident_next_step_actions,
    incident_profile_facts,
    incident_scalar,
    incident_timeline_rows,
)


def _humanized_gap(gap: str, *, korean: bool) -> str:
    """Render one evidence-gap key without exposing Markdown syntax tokens."""
    labels = (
        {
            "root_cause_missing": "근거에 기반한 근본 원인 가설",
            "impact_evidence_missing": "영향 근거",
            "grounded_citations_missing": "근거 인용",
            "incident_profile_missing": "인시던트 프로파일",
            "correlated_audit_truncated": "잘리지 않은 감사 기록",
        }
        if korean
        else {
            "root_cause_missing": "a grounded root-cause hypothesis",
            "impact_evidence_missing": "impact evidence",
            "grounded_citations_missing": "grounded citations",
            "incident_profile_missing": "the incident profile",
            "correlated_audit_truncated": "untruncated audit records",
        }
    )
    known = labels.get(gap)
    if known is not None:
        return known
    readable = gap.replace("_", " ").strip()
    return readable or gap


def incident_next_step_text(
    gaps: Sequence[str],
    *,
    korean: bool,
    root_cause: object = None,
) -> str:
    """Render read-only evidence collection guidance from measured Incident gaps."""
    actions = incident_next_step_actions(gaps, korean=korean)
    if not actions:
        if (
            isinstance(root_cause, Mapping)
            and root_cause.get("next_safe_step") == "configure_notification_route"
        ):
            return (
                "알림 전달을 다시 시도하기 전에 notification registry에 운영 알림 채널을 "
                "하나 이상 구성하세요."
                if korean
                else (
                    "Before retrying delivery, configure at least one operational-alert channel "
                    "in the notification registry."
                )
            )
        return (
            "상관된 감사 근거가 완전합니다. 변경을 제안하기 전에 기록된 활동을 검토하세요."
            if korean
            else (
                "The correlated audit evidence is complete. "
                "Review the recorded activity before proposing a change."
            )
        )
    if korean:
        if len(actions) == 1:
            return f"변경을 제안하기 전에 {actions[0]}."
        joined = " ".join(f"{action}." for action in actions)
        return f"변경을 제안하기 전에 다음을 수행하세요. {joined}"
    joined = actions[0] if len(actions) == 1 else ", ".join(actions[:-1]) + f", and {actions[-1]}"
    return f"Before proposing a change, {joined}."


def _timeline_markdown(
    rows: tuple[Mapping[str, str], ...],
    *,
    korean: bool,
) -> str:
    if not rows:
        return ""
    header = (
        "| 기록 시각 | 주체 | 활동 | 모드 | 감사 참조 |"
        if korean
        else "| Recorded | Actor | Activity | Mode | Audit ref |"
    )
    lines = [header, "| --- | --- | --- | --- | --- |"]
    lines.extend(
        f"| {row['recorded_at']} | {row['actor']} | {row['action_kind']} "
        f"| {row['mode']} | `{row['audit_ref']}` |"
        for row in rows
    )
    return "\n".join(lines)


def _profile_lines(
    facts: tuple[tuple[str, str], ...],
    profile: object,
    *,
    korean: bool,
) -> str:
    """Keep absent, unrecorded, and reported profile status distinct."""
    lines = "".join(f"- {label}: {value}\n" for label, value in facts)
    if profile is None:
        return lines + (
            "- 인시던트 프로파일이 없어 상태를 보고할 수 없습니다.\n"
            if korean
            else "- Status can't be reported because the incident profile is missing.\n"
        )
    status = profile.get("status") if isinstance(profile, Mapping) else None
    if incident_scalar(status) is None:
        return lines + (
            "- 조회한 감사 기록에 인시던트 상태가 없습니다.\n"
            if korean
            else "- The audit records read for this incident record no status.\n"
        )
    return lines


def render_incident_answer(
    request: SemanticTurnRequest,
    output: Mapping[str, object],
) -> str:
    """Render one bounded Incident answer without granting execution authority."""
    evidence = output.get("correlated_evidence")
    profile = output.get("incident_profile")
    root_cause = output.get("root_cause")
    gaps = output.get("evidence_gaps")
    shown = len(evidence) if isinstance(evidence, list) else 0
    verified = output.get("verified_records")
    evidence_count = (
        verified if isinstance(verified, int) and not isinstance(verified, bool) else shown
    )
    gap_values = (
        tuple(item for item in gaps if isinstance(item, str)) if isinstance(gaps, list) else ()
    )
    korean = request.locale.casefold().startswith("ko")
    facts = incident_profile_facts(profile, korean=korean)
    timeline = _timeline_markdown(incident_timeline_rows(evidence), korean=korean)
    timeline_truncated = shown > INCIDENT_TIMELINE_ROW_LIMIT
    missing = ", ".join(_humanized_gap(gap, korean=korean) for gap in gap_values) or (
        "없음" if korean else "none"
    )
    if korean:
        found = (
            f"- 상관관계가 있는 감사 기록 {evidence_count}건을 검증했습니다.\n"
            if evidence_count
            else "- 이 상관관계로 조회한 감사 기록이 없습니다.\n"
        )
        if shown < evidence_count:
            found += f"- 아래에는 가장 최근 {shown}건만 담겨 있습니다.\n"
        found += _profile_lines(facts, profile, korean=True)
        timeline_section = (
            "## 기록된 활동\n\n"
            + timeline
            + (
                f"\n\n표에는 가장 최근 {INCIDENT_TIMELINE_ROW_LIMIT}건만 담았습니다. "
                f"담긴 {shown}건 전체는 기술 상세에 있습니다.\n\n"
                if timeline_truncated
                else "\n\n"
            )
            if timeline
            else ""
        )
        return (
            "## 검증된 인시던트 근거\n\n"
            f"{found}\n"
            f"{timeline_section}"
            "## 제한 사항\n\n"
            f"- 누락된 근거: {missing}\n\n"
            "## 다음 안전 단계\n\n"
            "- ACTION_DRAFT 후보: "
            f"{incident_next_step_text(gap_values, korean=True, root_cause=root_cause)}\n\n"
            "이 결과는 읽기 전용이며 실행 권한을 부여하지 않습니다."
        )
    evidence_label = "record was" if evidence_count == 1 else "records were"
    found = (
        f"- {evidence_count} correlated audit {evidence_label} verified.\n"
        if evidence_count
        else "- No audit record was found for this correlation.\n"
    )
    if shown < evidence_count:
        found += f"- Only the most recent {shown} are carried below.\n"
    found += _profile_lines(facts, profile, korean=False)
    timeline_section = (
        "## Recorded activity\n\n"
        + timeline
        + (
            f"\n\nThe table lists only the most recent {INCIDENT_TIMELINE_ROW_LIMIT} records. "
            f"All {shown} carried records are in technical details.\n\n"
            if timeline_truncated
            else "\n\n"
        )
        if timeline
        else ""
    )
    return (
        "## Verified incident evidence\n\n"
        f"{found}\n"
        f"{timeline_section}"
        "## Limitations\n\n"
        f"- Missing evidence: {missing}\n\n"
        "## Next safe step\n\n"
        "- Candidate ACTION_DRAFT: "
        f"{incident_next_step_text(gap_values, korean=False, root_cause=root_cause)}\n\n"
        "This result is read-only and grants no execution authority."
    )
