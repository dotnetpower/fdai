"""Deterministic verification of operational and incident evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_incident_dossier import render_incident_dossier
from fdai.delivery.operator_api.routes.chat_verification_rendering import (
    agent_activity_lines,
    incident_summary_line,
    integer,
    mappings,
    notification_delivery_lines,
    optional_text,
    recorded_detection_lines,
    recorded_failure_lines,
    strings,
    text,
    topic_text,
)
from fdai.delivery.operator_api.routes.chat_verification_result import (
    VerificationPayload,
    VerificationStatus,
)

Changed = Callable[[str, str], VerificationStatus]


def verify_operational_evidence(
    provisional: str,
    raw: Mapping[str, Any],
    *,
    locale: str | None,
    changed: Changed,
) -> VerificationPayload:
    """Render one terminal result from server-owned operational evidence."""

    evidence = dict(raw)
    state = evidence.get("status")
    korean = _is_korean(locale)
    if state == "unavailable":
        answer = (
            "운영 근거 조회를 완료하지 못해 현재 답변을 검증할 수 없습니다. 잠시 후 다시 "
            "시도해 주세요."
            if korean
            else "Operational evidence could not be retrieved, so this answer could not be "
            "verified. Try again shortly."
        )
        return _result("unverified", answer, "evidence_unavailable")
    if state == "none":
        evidence_reason = evidence.get("reason")
        if evidence_reason in {
            "selected incident context is invalid",
            "selected incident is not available in the server read model",
        }:
            answer = (
                "선택된 incident context가 유효하지 않거나 현재 server read model에서 사용할 수 "
                "없습니다. Incident를 다시 선택해 주세요."
                if korean
                else (
                    "The selected incident context is invalid or no longer available in the "
                    "server read model. Select the incident again."
                )
            )
            return VerificationPayload(
                status="unverified",
                answer=answer,
                authority="server_read_model",
                checks_completed=0,
                checks_total=1,
                reason_code="selected_incident_context_unavailable",
            )
        searched = integer(evidence.get("searched_recent_incidents"))
        topics = strings(evidence.get("topic_terms"))
        scope = str(searched) if searched is not None else "the bounded recent set"
        topic = topic_text(topics, korean=korean)
        answer = (
            f"최근 인시던트 {scope}건을 "
            f"확인했지만 {topic}와 일치하는 "
            "사건은 없었습니다. 이 "
            "제한된 검색 범위에서는 "
            "원인을 확정할 수 없습니다."
            if korean and searched is not None
            else (
                f"제한된 최근 인시던트 "
                f"범위에서 {topic}와 일치하는 "
                "사건을 찾지 못했습니다. "
                "따라서 원인을 확정할 수 "
                "없습니다."
                if korean
                else f"The {scope} incidents searched contained no match for {topic}. "
                "No cause can be established from this bounded search."
            )
        )
        search_refs = (f"incident-search:recent:{searched}",) if searched is not None else ()
        return _result(
            changed(provisional, answer),
            answer,
            "no_matching_incident",
            search_refs,
        )
    if state == "summary":
        incidents = mappings(evidence.get("incidents"))
        searched = integer(evidence.get("searched_recent_incidents"))
        lines = [incident_summary_line(item, korean=korean) for item in incidents]
        count = len(lines)
        answer = (
            f"최근 인시던트 {count}건 요약입니다:\n"
            if korean
            else f"Summary of {count} recent incident(s):\n"
        ) + "\n".join(lines)
        if searched is not None and searched > count:
            answer += (
                f"\n최근 {searched}건을 검색해 일치한 {count}건을 표시했습니다."
                if korean
                else f"\nSearched {searched} recent incidents and displayed {count} matches."
            )
        summary_refs = tuple(
            f"incident:{correlation}"
            for item in incidents
            if (correlation := optional_text(item.get("correlation_id"))) is not None
        )
        return _result(
            changed(provisional, answer),
            answer,
            "incident_summary",
            summary_refs,
        )
    if state == "ambiguous":
        candidates = mappings(evidence.get("candidates"))[:5]
        lines = [
            f"- {text(item.get('correlation_id'), 'unknown')}: "
            f"{text(item.get('title'), 'untitled')}"
            for item in candidates
        ]
        answer = (
            "여러 인시던트가 질문과 동일하게 일치합니다. 확인할 대상을 선택해 주세요:\n"
            if korean
            else "Multiple incidents match the question equally. Choose one to verify:\n"
        ) + "\n".join(lines)
        candidate_refs = tuple(
            f"incident:{correlation}"
            for item in candidates
            if (correlation := optional_text(item.get("correlation_id"))) is not None
        )
        return _result(
            changed(provisional, answer),
            answer,
            "ambiguous_incident",
            candidate_refs,
        )
    if state != "matched":
        answer = (
            "운영 근거 상태를 확인할 수 없어 답변을 검증하지 못했습니다."
            if korean
            else "The operational evidence state was not recognized, so the answer is unverified."
        )
        return _result("unverified", answer, "unknown_evidence_state")

    selected = evidence.get("selected_incident")
    incident = dict(selected) if isinstance(selected, Mapping) else {}
    correlation = text(incident.get("correlation_id"), "unknown")
    title = text(incident.get("title"), "untitled incident")
    incident_status = text(incident.get("status"), "unknown")
    recorded_at = text(incident.get("last_updated_at"), "unknown time")
    dossier = render_incident_dossier(evidence, locale=locale)
    if dossier is not None:
        return VerificationPayload(
            status=changed(provisional, dossier.answer) if dossier.verified else "unverified",
            answer=dossier.answer,
            authority="server_read_model",
            checks_completed=1 if dossier.verified else 0,
            checks_total=1,
            evidence_refs=dossier.evidence_refs,
            reason_code=dossier.reason_code,
        )
    activities = agent_activity_lines(evidence, korean=korean)
    activity_suffix = (
        ("\n\n기록된 에이전트 활동:\n" if korean else "\n\nRecorded agent activity:\n")
        + "\n".join(activities)
        if activities
        else (
            "\n\n사용 가능한 감사 근거에는 에이전트별 활동이 기록되어 있지 않습니다."
            if korean
            else "\n\nNo agent-specific activity is recorded in the available audit evidence."
        )
    )
    hypotheses = mappings(evidence.get("grounded_hypotheses"))
    refs: list[str] = [f"incident:{correlation}"]
    if hypotheses:
        hypothesis = hypotheses[0]
        cause = text(hypothesis.get("cause"), "")
        citations = mappings(hypothesis.get("citations"))
        refs.extend(
            f"{text(item.get('kind'), 'evidence')}:{text(item.get('ref'), 'unknown')}"
            for item in citations
        )
        answer = (
            f"{correlation} ({title})의 상태는 {incident_status}이며, "
            "검증된 원인은 "
            f"다음과 같습니다: {cause} 마지막 "
            f"근거 시각은 {recorded_at}입니다."
            f"{activity_suffix}"
            if korean
            else f"The verified cause for {correlation} ({title}) is: {cause} "
            f"The incident status is {incident_status}. The latest evidence is from "
            f"{recorded_at}.{activity_suffix}"
        )
        return _result(changed(provisional, answer), answer, "grounded_rca", tuple(refs))

    detection_lines, detection_refs = recorded_detection_lines(evidence, korean=korean)
    failure_lines, failure_refs = recorded_failure_lines(evidence)
    delivery_lines, delivery_refs = notification_delivery_lines(evidence)
    detection_section = (
        ("\n감지된 workload 상태:\n" if korean else "\nDetected workload condition:\n")
        + "\n".join(detection_lines)
        if detection_lines
        else ""
    )
    delivery_section = (
        ("\n\n알림 전달 문제:\n" if korean else "\n\nNotification delivery issue:\n")
        + "\n".join(delivery_lines)
        if delivery_lines
        else ""
    )
    if failure_lines:
        refs.extend((*detection_refs, *failure_refs, *delivery_refs))
        recorded_failures = "\n".join(failure_lines)
        answer = (
            f"{correlation} ({title})의 상태는 {incident_status}이며 "
            f"{recorded_at}에 마지막으로 "
            f"갱신되었습니다.{detection_section}\n\ncitation을 갖춘 grounded "
            "root cause는 기록되지 않았지만, "
            "workload 감사 로그에 다음 실패 "
            "이유가 기록되어 있습니다:\n"
            f"{recorded_failures}\n이 내용은 관찰된 "
            "실패 이유이며 완전한 RCA는 "
            f"아닙니다.{delivery_section}"
            f"{activity_suffix}"
            if korean
            else f"{correlation} ({title}) is {incident_status} and was last updated at "
            f"{recorded_at}.{detection_section}\n\nNo citation-grounded root cause is recorded, "
            "but the workload audit log "
            f"records this failure reason:\n{recorded_failures}\nThis is an observed failure "
            f"reason, not a complete RCA.{delivery_section}{activity_suffix}"
        )
        return _result(
            changed(provisional, answer),
            answer,
            "recorded_failure_reason",
            tuple(refs),
        )

    if detection_lines:
        refs.extend((*detection_refs, *delivery_refs))
        answer = (
            f"{correlation} ({title})의 상태는 {incident_status}이며 "
            f"{recorded_at}에 마지막으로 갱신되었습니다.{detection_section}\n\n"
            "이 근거는 감지된 증상과 대상만 확인하며 원인을 증명하지 않습니다. "
            "citation을 갖춘 grounded root cause는 아직 기록되지 않았습니다."
            f"{delivery_section}{activity_suffix}"
            if korean
            else f"{correlation} ({title}) is {incident_status} and was last updated at "
            f"{recorded_at}.{detection_section}\n\nThis evidence confirms the detected condition "
            "and target, not its cause. No citation-grounded root cause is recorded yet."
            f"{delivery_section}{activity_suffix}"
        )
        return _result(
            changed(provisional, answer),
            answer,
            "detected_condition_without_rca",
            tuple(refs),
        )

    if delivery_lines:
        refs.extend(delivery_refs)
        recorded_failures = "\n".join(delivery_lines)
        answer = (
            f"{correlation} ({title})의 상태는 {incident_status}이며 "
            f"{recorded_at}에 마지막으로 갱신되었습니다. 감사 로그에 다음 알림 전달 "
            f"실패가 기록되어 있습니다:\n{recorded_failures}\n이 내용은 관찰된 전달 실패이며 "
            f"완전한 RCA는 아닙니다.{activity_suffix}"
            if korean
            else f"{correlation} ({title}) is {incident_status} and was last updated at "
            f"{recorded_at}. The audit log records this notification delivery failure:\n"
            f"{recorded_failures}\nThis is an observed delivery failure, not a complete RCA."
            f"{activity_suffix}"
        )
        return _result(
            changed(provisional, answer),
            answer,
            "recorded_failure_reason",
            tuple(refs),
        )

    answer = (
        f"{correlation} ({title})의 상태는 {incident_status}이며 "
        f"{recorded_at}에 마지막으로 "
        "갱신되었지만, citation을 갖춘 grounded "
        "root cause는 기록되지 않았습니다. "
        f"원인을 확정할 수 없습니다.{activity_suffix}"
        if korean
        else f"{correlation} ({title}) is {incident_status} and was last updated at "
        f"{recorded_at}, but no grounded root cause with citations is recorded. "
        f"The cause cannot be confirmed.{activity_suffix}"
    )
    return _result(
        changed(provisional, answer),
        answer,
        "no_grounded_rca",
        tuple(refs),
    )


def _result(
    status: VerificationStatus,
    answer: str,
    reason_code: str,
    refs: tuple[str, ...] = (),
) -> VerificationPayload:
    return VerificationPayload(
        status=status,
        answer=answer,
        authority="server_read_model",
        checks_completed=1,
        checks_total=1,
        evidence_refs=refs,
        reason_code=reason_code,
    )


def _is_korean(locale: str | None) -> bool:
    if locale is None:
        return False
    return locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko"
