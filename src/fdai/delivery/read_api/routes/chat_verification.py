"""Deterministic terminal verification for progressive Command Deck answers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai.delivery.read_api.routes.chat_behavior_evidence import (
    behavior_evidence_refs,
    render_behavior_answer,
)
from fdai.delivery.read_api.routes.chat_claims import (
    AtomicClaim,
    EvidenceManifest,
    ScreenClaimResult,
    verify_screen_claims,
)
from fdai.delivery.read_api.routes.chat_current_time import (
    current_time_evidence_refs,
    render_current_time_answer,
)
from fdai.delivery.read_api.routes.chat_data_sources import (
    read_source_evidence_refs,
    render_read_source_answer,
)
from fdai.delivery.read_api.routes.chat_detection_readiness import (
    detection_readiness_evidence_refs,
    render_detection_readiness_answer,
)
from fdai.delivery.read_api.routes.chat_inventory import (
    inventory_evidence_refs,
    render_inventory_answer,
)
from fdai.delivery.read_api.routes.chat_log_query import (
    log_query_evidence_refs,
    render_log_query_answer,
)
from fdai.delivery.read_api.routes.chat_prompt_ontology import (
    _render_ontology_storage_answer,
)
from fdai.delivery.read_api.routes.chat_subscription_health import (
    render_subscription_health_answer,
    subscription_health_evidence_refs,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    agent_activity_lines as _agent_activity_lines,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    incident_summary_line as _incident_summary_line,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    integer as _integer,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    mappings as _mappings,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    optional_text as _optional_text,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    recorded_failure_lines as _recorded_failure_lines,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    strings as _strings,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    text as _text,
)
from fdai.delivery.read_api.routes.chat_verification_rendering import (
    topic_text as _topic_text,
)
from fdai.delivery.read_api.routes.chat_verification_text import (
    answer_text_is_well_formed,
    answers_match,
)

VerificationStatus = Literal["verified", "consistent", "corrected", "unverified"]

_AGENT_SELF_CAPABILITY_QUESTION = re.compile(
    r"\b(?:what\s+do\s+you\s+do|what\s+is\s+your\s+role|what\s+are\s+your\s+"
    r"responsibilities|describe\s+your\s+role|your\s+primary\s+work)\b"
    r"|(?:너|네|당신)(?:는|가)?\s*(?:주로\s*)?(?:어떤|무슨)?\s*(?:일|역할)"
    r"|(?:무슨\s*일|뭐\s*하는\s*일|담당하는\s*일)",
    re.IGNORECASE,
)
_AGENT_STATE_REF = re.compile(r"^agent-state:([A-Za-z][A-Za-z0-9-]*):sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AnswerVerification:
    """Canonical answer plus the trust state the UI may render."""

    status: VerificationStatus
    answer: str
    authority: str
    checks_completed: int
    checks_total: int
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None
    claims: tuple[AtomicClaim, ...] = ()
    evidence_manifest: EvidenceManifest | None = None
    failed_claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "authority": self.authority,
            "checks_completed": self.checks_completed,
            "checks_total": self.checks_total,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "claims": [claim.to_dict() for claim in self.claims],
            "failed_claim_ids": list(self.failed_claim_ids),
        }
        if self.evidence_manifest is not None:
            payload["evidence_manifest"] = self.evidence_manifest.to_dict()
        return payload


def verify_answer(
    provisional: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification:
    """Verify one provisional answer and return its canonical revision.

    Screen-only answers can only be checked for consistency with the supplied
    browser snapshot. Operational answers are replaced with deterministic prose
    rendered from the server-owned evidence state, so unsupported model text
    never becomes the terminal conversation history.
    """

    if not answer_text_is_well_formed(provisional):
        korean = _is_korean(locale)
        return AnswerVerification(
            status="unverified",
            answer=(
                "답변에 유효하지 않은 문자가 포함되어 확정하지 않았습니다. 다시 시도해 주세요."
                if korean
                else "The answer contained invalid characters and was not finalized. Try again."
            ),
            authority="answer_text_integrity",
            checks_completed=0,
            checks_total=1,
            reason_code="answer_text_invalid",
        )

    ontology_storage = view_context.get("_ontology_storage_contract")
    if isinstance(ontology_storage, Mapping):
        ontology_answer = _render_ontology_storage_answer(ontology_storage, locale=locale)
        evidence_ref = ontology_storage.get("evidence_ref")
        if ontology_answer is None or not isinstance(evidence_ref, str):
            return AnswerVerification(
                status="unverified",
                answer="Ontology catalog storage evidence could not be rendered.",
                authority="ontology_catalog",
                checks_completed=0,
                checks_total=1,
                reason_code="ontology_storage_evidence_invalid",
            )
        return AnswerVerification(
            status=_changed(provisional, ontology_answer),
            answer=ontology_answer,
            authority="ontology_catalog",
            checks_completed=1,
            checks_total=1,
            evidence_refs=(evidence_ref,),
            reason_code="ontology_storage_contract",
        )

    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping) and tool.get("tool") == "get_current_time":
        time_answer = render_current_time_answer(tool, locale=locale)
        if time_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Server-clock evidence could not be rendered.",
                authority="server_clock",
                checks_completed=0,
                checks_total=1,
                reason_code="current_time_evidence_invalid",
            )
        time_refs = current_time_evidence_refs(tool)
        return AnswerVerification(
            status=_changed(provisional, time_answer),
            answer=time_answer,
            authority="server_clock",
            checks_completed=1,
            checks_total=1,
            evidence_refs=time_refs,
            reason_code="current_time_grounded",
        )

    if isinstance(tool, Mapping) and tool.get("tool") == "describe_read_sources":
        source_answer = render_read_source_answer(tool, locale=locale)
        if source_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Read-source manifest evidence could not be rendered.",
                authority="server_read_source_manifest",
                checks_completed=0,
                checks_total=1,
                reason_code="read_source_manifest_invalid",
            )
        source_refs = read_source_evidence_refs(tool)
        return AnswerVerification(
            status=_changed(provisional, source_answer),
            answer=source_answer,
            authority="server_read_source_manifest",
            checks_completed=len(source_refs),
            checks_total=len(source_refs),
            evidence_refs=source_refs,
            reason_code="read_source_manifest_grounded",
        )

    if isinstance(tool, Mapping) and tool.get("tool") == "query_log":
        log_answer = render_log_query_answer(tool, locale=locale)
        if log_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Azure Monitor Logs evidence could not be rendered.",
                authority="server_log_query",
                checks_completed=0,
                checks_total=1,
                reason_code="log_query_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        log_refs = log_query_evidence_refs(tool)
        if state in {"matched", "empty"}:
            return AnswerVerification(
                status=_changed(provisional, log_answer),
                answer=log_answer,
                authority="server_log_query",
                checks_completed=1,
                checks_total=1,
                evidence_refs=log_refs,
                reason_code="log_query_bounded",
            )
        return AnswerVerification(
            status="unverified",
            answer=log_answer,
            authority="server_log_query",
            checks_completed=0,
            checks_total=1,
            evidence_refs=log_refs,
            reason_code="log_query_unavailable",
        )

    if isinstance(tool, Mapping) and tool.get("tool") == "query_detection_readiness":
        readiness_answer = render_detection_readiness_answer(tool, locale=locale)
        if readiness_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Detection readiness evidence could not be rendered.",
                authority="server_detection_readiness",
                checks_completed=0,
                checks_total=1,
                reason_code="detection_readiness_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        readiness_refs = detection_readiness_evidence_refs(tool)
        return AnswerVerification(
            status=(
                _changed(provisional, readiness_answer)
                if state in {"matched", "empty"}
                else "unverified"
            ),
            answer=readiness_answer,
            authority="server_detection_readiness",
            checks_completed=1 if state in {"matched", "empty"} else 0,
            checks_total=1,
            evidence_refs=readiness_refs,
            reason_code=(
                "detection_readiness_snapshot_grounded"
                if state in {"matched", "empty"}
                else "detection_readiness_unavailable"
            ),
        )

    if isinstance(tool, Mapping) and tool.get("tool") == "query_inventory":
        inventory_answer = render_inventory_answer(tool, locale=locale)
        if inventory_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Azure inventory evidence could not be rendered.",
                authority="server_inventory_graph",
                checks_completed=0,
                checks_total=1,
                reason_code="inventory_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        inventory_activity = bool(
            isinstance(result, Mapping) and result.get("query_source") == "activity"
        )
        inventory_authority = (
            "server_inventory_activity" if inventory_activity else "server_inventory_graph"
        )
        inventory_refs = inventory_evidence_refs(tool)
        if state == "matched":
            return AnswerVerification(
                status=_changed(provisional, inventory_answer),
                answer=inventory_answer,
                authority=inventory_authority,
                checks_completed=1,
                checks_total=1,
                evidence_refs=inventory_refs,
                reason_code=(
                    "inventory_activity_grounded"
                    if inventory_activity
                    else "inventory_snapshot_grounded"
                ),
            )
        if state == "partial":
            return AnswerVerification(
                status="unverified",
                answer=inventory_answer,
                authority="server_inventory_graph",
                checks_completed=1,
                checks_total=2,
                evidence_refs=inventory_refs,
                reason_code="inventory_workload_coverage_gap",
            )
        return AnswerVerification(
            status="unverified",
            answer=inventory_answer,
            authority=inventory_authority,
            checks_completed=0,
            checks_total=1,
            evidence_refs=inventory_refs,
            reason_code="inventory_evidence_unavailable",
        )

    if isinstance(tool, Mapping) and tool.get("tool") == "query_subscription_health":
        health_answer = render_subscription_health_answer(tool, locale=locale)
        if health_answer is None:
            return AnswerVerification(
                status="unverified",
                answer="Azure subscription health evidence could not be rendered.",
                authority="server_subscription_health",
                checks_completed=0,
                checks_total=1,
                reason_code="subscription_health_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        health_refs = subscription_health_evidence_refs(tool)
        if state == "matched":
            return AnswerVerification(
                status=_changed(provisional, health_answer),
                answer=health_answer,
                authority="server_subscription_health",
                checks_completed=1,
                checks_total=1,
                evidence_refs=health_refs,
                reason_code="subscription_health_grounded",
            )
        if state == "partial":
            return AnswerVerification(
                status="unverified",
                answer=health_answer,
                authority="server_subscription_health",
                checks_completed=0,
                checks_total=1,
                evidence_refs=health_refs,
                reason_code="subscription_health_partial",
            )
        return AnswerVerification(
            status="unverified",
            answer=health_answer,
            authority="server_subscription_health",
            checks_completed=0,
            checks_total=1,
            evidence_refs=health_refs,
            reason_code="subscription_health_unavailable",
        )

    behavior = view_context.get("_behavior_evidence")
    if isinstance(behavior, Mapping):
        answer = render_behavior_answer(behavior, locale=locale)
        state = behavior.get("status")
        behavior_refs = behavior_evidence_refs(behavior)
        if state in {"matched", "comparison"}:
            return AnswerVerification(
                status=_changed(provisional, answer),
                answer=answer,
                authority="behavior_knowledge_index",
                checks_completed=len(behavior_refs),
                checks_total=len(behavior_refs),
                evidence_refs=behavior_refs,
                reason_code="behavior_contract_fresh",
            )
        reason = {
            "stale": "behavior_source_stale",
            "conflict": "behavior_contract_conflict",
            "none": "behavior_evidence_absent",
            "unavailable": "behavior_index_unavailable",
        }.get(str(state), "behavior_evidence_unknown")
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="behavior_knowledge_index",
            checks_completed=0,
            checks_total=max(1, len(behavior_refs)),
            evidence_refs=behavior_refs,
            reason_code=reason,
        )

    raw = view_context.get("_operational_evidence")
    agent = view_context.get("_agent_evidence")
    if isinstance(agent, Mapping):
        handoff_from = agent.get("handoff_from")
        agent_answer = agent.get("answer")
        if (
            not isinstance(raw, Mapping)
            and isinstance(handoff_from, str)
            and not (isinstance(agent_answer, str) and agent_answer.strip())
        ):
            korean = _is_korean(locale)
            answer = (
                f"요청한 {handoff_from} 응답에서 근거를 확인하지 못해 Bragi가 현재 화면만으로 "
                "답변하지 않았습니다. 에이전트 근거가 준비된 뒤 다시 시도하거나 특정 "
                "인시던트 또는 리소스를 지정해 주세요."
                if korean
                else f"{handoff_from} could not provide grounded evidence for this request, so "
                "Bragi did not answer from the current screen. Retry after agent evidence is "
                "available or ask about a specific incident or resource."
            )
            return AnswerVerification(
                status="unverified",
                answer=answer,
                authority="pantheon_runtime",
                checks_completed=0,
                checks_total=1,
                reason_code="agent_evidence_unavailable",
            )
        capability = _verify_agent_self_capability(
            provisional,
            view_context,
            agent,
            locale=locale,
        )
        if capability is not None:
            return capability

    if not isinstance(raw, Mapping):
        screen = verify_screen_claims(provisional, view_context)
        if screen.overflow or not screen.manifest.complete or not screen.supported:
            concept_correction = _correct_concept_scope_additions(
                provisional,
                view_context,
                screen.claims,
            )
            if concept_correction is not None:
                corrected, corrected_screen = concept_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="concept_scope_claims_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            screen_correction = _correct_screen_unsupported_sentences(
                provisional,
                view_context,
                screen,
            )
            if screen_correction is not None:
                corrected, corrected_screen = screen_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="screen_unsupported_sentences_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            korean = _is_korean(locale)
            answer = (
                "현재 화면 근거로 답변의 "
                "모든 사실 claim을 확인할 수 "
                "없어 답변을 확정하지 "
                "않았습니다. 화면의 범위를 "
                "줄이거나 구체적인 항목을 "
                "선택한 뒤 다시 질문해 주세요."
                if korean
                else "Not every factual claim could be confirmed from the current screen, "
                "so the answer was not finalized. Narrow the screen or select a specific "
                "item and ask again."
            )
            reason = (
                "screen_claim_overflow"
                if screen.overflow
                else (
                    "screen_snapshot_incomplete"
                    if not screen.manifest.complete
                    else "screen_claim_mismatch"
                )
            )

            return AnswerVerification(
                status="unverified",
                answer=answer,
                authority=screen.manifest.authority,
                checks_completed=sum(1 for claim in screen.claims if claim.status == "supported"),
                checks_total=len(screen.claims),
                evidence_refs=tuple(
                    dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
                ),
                reason_code=reason,
                claims=screen.claims,
                evidence_manifest=screen.manifest,
                failed_claim_ids=screen.failed_claim_ids,
            )
        return AnswerVerification(
            status="consistent",
            answer=provisional,
            authority=screen.manifest.authority,
            checks_completed=len(screen.claims),
            checks_total=len(screen.claims),
            evidence_refs=tuple(
                dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
            ),
            reason_code=(
                "screen_claims_supported" if screen.claims else "screen_no_checkable_claims"
            ),
            claims=screen.claims,
            evidence_manifest=screen.manifest,
        )

    evidence = dict(raw)
    state = evidence.get("status")
    korean = _is_korean(locale)
    if state == "unavailable":
        answer = (
            "운영 근거 조회를 완료하지 "
            "못해 현재 답변을 검증할 수 "
            "없습니다. 잠시 후 다시 "
            "시도해 주세요."
            if korean
            else "Operational evidence could not be retrieved, so this answer could not be "
            "verified. Try again shortly."
        )
        return _result("unverified", answer, "evidence_unavailable")
    if state == "none":
        searched = _integer(evidence.get("searched_recent_incidents"))
        topics = _strings(evidence.get("topic_terms"))
        scope = str(searched) if searched is not None else "the bounded recent set"
        topic = _topic_text(topics, korean=korean)
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
            _changed(provisional, answer),
            answer,
            "no_matching_incident",
            search_refs,
        )
    if state == "summary":
        incidents = _mappings(evidence.get("incidents"))
        searched = _integer(evidence.get("searched_recent_incidents"))
        lines = [_incident_summary_line(item, korean=korean) for item in incidents]
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
            if (correlation := _optional_text(item.get("correlation_id"))) is not None
        )
        return _result(
            _changed(provisional, answer),
            answer,
            "incident_summary",
            summary_refs,
        )
    if state == "ambiguous":
        candidates = _mappings(evidence.get("candidates"))[:5]
        lines = [
            f"- {_text(item.get('correlation_id'), 'unknown')}: "
            f"{_text(item.get('title'), 'untitled')}"
            for item in candidates
        ]
        answer = (
            "여러 인시던트가 질문과 동일하게 일치합니다. 확인할 대상을 선택해 주세요:\n"
            if korean
            else "Multiple incidents match the question equally. Choose one to verify:\n"
        ) + "\n".join(lines)
        candidate_refs = tuple(
            f"incident:{corr}"
            for item in candidates
            if (corr := _optional_text(item.get("correlation_id"))) is not None
        )
        return _result(
            _changed(provisional, answer),
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
    correlation = _text(incident.get("correlation_id"), "unknown")
    title = _text(incident.get("title"), "untitled incident")
    incident_status = _text(incident.get("status"), "unknown")
    recorded_at = _text(incident.get("last_updated_at"), "unknown time")
    activities = _agent_activity_lines(evidence, korean=korean)
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
    hypotheses = _mappings(evidence.get("grounded_hypotheses"))
    refs: list[str] = [f"incident:{correlation}"]
    if hypotheses:
        hypothesis = hypotheses[0]
        cause = _text(hypothesis.get("cause"), "")
        citations = _mappings(hypothesis.get("citations"))
        refs.extend(
            f"{_text(item.get('kind'), 'evidence')}:{_text(item.get('ref'), 'unknown')}"
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
        return _result(_changed(provisional, answer), answer, "grounded_rca", tuple(refs))

    failure_lines, failure_refs = _recorded_failure_lines(evidence)
    if failure_lines:
        refs.extend(failure_refs)
        recorded_failures = "\n".join(failure_lines)
        answer = (
            f"{correlation} ({title})의 상태는 {incident_status}이며 "
            f"{recorded_at}에 마지막으로 "
            "갱신되었습니다. citation을 갖춘 grounded "
            "root cause는 기록되지 않았지만, "
            "감사 로그에 다음 실패 "
            "이유가 기록되어 있습니다:\n"
            f"{recorded_failures}\n이 내용은 관찰된 "
            "실패 이유이며 완전한 RCA는 "
            "아닙니다."
            f"{activity_suffix}"
            if korean
            else f"{correlation} ({title}) is {incident_status} and was last updated at "
            f"{recorded_at}. No citation-grounded root cause is recorded, but the audit log "
            f"records this failure reason:\n{recorded_failures}\nThis is an observed failure "
            f"reason, not a complete RCA.{activity_suffix}"
        )
        return _result(
            _changed(provisional, answer),
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
        _changed(provisional, answer),
        answer,
        "no_grounded_rca",
        tuple(refs),
    )


def _result(
    status: VerificationStatus,
    answer: str,
    reason_code: str,
    refs: tuple[str, ...] = (),
) -> AnswerVerification:
    return AnswerVerification(
        status=status,
        answer=answer,
        authority="server_read_model",
        checks_completed=1,
        checks_total=1,
        evidence_refs=refs,
        reason_code=reason_code,
    )


def _verify_agent_self_capability(
    provisional: str,
    view_context: Mapping[str, Any],
    agent_evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification | None:
    """Render a selected agent's role only from its content-addressed capability facts."""

    plan = view_context.get("_answer_plan")
    subject = plan.get("subject") if isinstance(plan, Mapping) else None
    if not isinstance(subject, str) or _AGENT_SELF_CAPABILITY_QUESTION.search(subject) is None:
        return None
    primary_agent = _optional_text(agent_evidence.get("primary_agent"))
    facts = agent_evidence.get("facts")
    if primary_agent is None or not isinstance(facts, Mapping):
        return None
    fact_agent = _optional_text(facts.get("agent"))
    layer = _optional_text(facts.get("layer"))
    owns = _strings(facts.get("owns"))
    domains = _strings(facts.get("question_domains"))
    refs = tuple(
        ref
        for ref in _strings(facts.get("evidence_refs"))
        if (match := _AGENT_STATE_REF.fullmatch(ref)) is not None
        and match.group(1) == primary_agent
    )
    if fact_agent != primary_agent or layer is None or not owns or not domains or not refs:
        return None

    owned_text = ", ".join(owns)
    domain_text = ", ".join(domain.replace("_", " ") for domain in domains)
    if _is_korean(locale):
        layer_text = {
            "pipeline": "파이프라인",
            "domain": "도메인",
            "governance": "거버넌스",
        }.get(layer, layer)
        answer = (
            f"저는 {primary_agent}이며 {layer_text} 계층의 에이전트입니다. "
            f"주로 {owned_text} 관련 신호를 담당합니다. "
            f"{domain_text} 영역의 질문에 답합니다."
        )
    else:
        answer = (
            f"I am {primary_agent}, a {layer}-layer agent. "
            f"My primary owned signals are {owned_text}. "
            f"I answer questions about {domain_text}."
        )
    return AnswerVerification(
        status=_changed(provisional, answer),
        answer=answer,
        authority="pantheon_runtime",
        checks_completed=1,
        checks_total=1,
        evidence_refs=tuple(dict.fromkeys(refs)),
        reason_code="agent_capability_facts",
    )


def _changed(provisional: str, canonical: str) -> VerificationStatus:
    return "verified" if answers_match(provisional, canonical) else "corrected"


def _correct_concept_scope_additions(
    answer: str,
    view_context: Mapping[str, Any],
    claims: Sequence[AtomicClaim],
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported scope-only addenda from a glossary answer once."""

    if not isinstance(view_context.get("_concept_evidence"), Mapping):
        return None
    failed = tuple(claim for claim in claims if claim.status != "supported")
    if not failed or any(claim.kind != "scope" for claim in failed):
        return None
    corrected = answer
    for claim in sorted(failed, key=lambda item: item.start, reverse=True):
        corrected = corrected[: claim.start] + corrected[claim.end :]
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if verified.overflow or not verified.manifest.complete or not verified.supported:
        return None
    return corrected, verified


def _correct_screen_unsupported_sentences(
    answer: str,
    view_context: Mapping[str, Any],
    result: ScreenClaimResult,
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported sentences when other screen claims are grounded."""

    if result.overflow or not result.manifest.complete:
        return None
    failed = tuple(claim for claim in result.claims if claim.status != "supported")
    supported = tuple(claim for claim in result.claims if claim.status == "supported")
    if not failed or not supported:
        return None
    corrected = answer
    for sentence in sorted({claim.text for claim in failed}, key=len, reverse=True):
        corrected = corrected.replace(sentence, "")
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if (
        verified.overflow
        or not verified.manifest.complete
        or not verified.supported
        or not verified.claims
    ):
        return None
    return corrected, verified


def _is_korean(locale: str | None) -> bool:
    if locale is None:
        return False
    return locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko"


__all__ = [
    "AnswerVerification",
    "VerificationStatus",
    "verify_answer",
]
