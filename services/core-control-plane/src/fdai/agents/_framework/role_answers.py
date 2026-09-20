"""Deterministic localized role answers for Pantheon conversational ports."""

from __future__ import annotations

from collections.abc import Mapping


def _mapping_count(facts: Mapping[str, object], key: str) -> int:
    value = facts.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} role fact MUST be a mapping")
    return len(value)


def bragi_role_answer(locale: str, agent_count: int, evidence_ref: str) -> str:
    if locale == "ko":
        return (
            "저는 파이프라인 서술기이자 번역기인 Bragi입니다. Thor에게 보고합니다. "
            "Conversation, Turn, UserPreference, HandoffEscalation 및 PostTurnReview를 "
            "소유합니다. 검증된 semantic judgment로 읽기 전용 질문을 담당 에이전트에게 "
            "라우팅하고 동일한 근거를 운영자 로캘로 표현합니다. 모델 출력은 표현 전용이며 "
            "판단, 승인, 근거 변경 또는 실행 권한을 갖지 않습니다. 작업 요청은 운영자를 "
            "initiator로 유지한 채 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 "
            f"시스템 프롬프트는 공개하지 않습니다. 현재 고정된 에이전트 {agent_count}개를 "
            f"라우팅할 수 있습니다. 근거: {evidence_ref}."
        )
    return (
        "I am Bragi, the pipeline narrator and translator. I report to Thor. I own Conversation, "
        "Turn, UserPreference, HandoffEscalation, and PostTurnReview. I use verified semantic "
        "judgment to route read-only questions to the accountable agent and render the same "
        "evidence in the operator's locale. Model output is presentation-only and has no judgment, "
        "approval, evidence-mutation, or execution authority. Action requests must re-enter the "
        "typed pipeline with the operator retained as initiator. I do not reveal hidden system "
        f"prompts. I can route across the fixed roster of {agent_count} agents. "
        f"Evidence: {evidence_ref}."
    )


def forseti_role_answer(locale: str, facts: Mapping[str, object], evidence_ref: str) -> str:
    if locale == "ko":
        return (
            "저는 근거에 기반한 판정을 발행하는 파이프라인 judge인 Forseti입니다. Thor가 아닌 "
            "Odin에게 보고합니다. 결정론적 규칙과 정책을 먼저 적용하며 잔여 모호성에만 검증이 "
            "적용된 T2를 사용합니다. Verdict, SecurityEvent, ArbitrationRequest 및 "
            "ProspectiveLineage를 게시하며 근거가 있는 RCA는 core causal-hypothesis "
            "projection으로 유지합니다. 작업을 승인하거나 실행하지 않습니다. 이 대화 "
            "포트는 읽기 전용이며 작업 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 "
            "진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 않습니다. 구성된 위험 표에는 "
            f"ActionType {_mapping_count(facts, 'known_action_verdicts')}개와 규칙 일치 항목 "
            f"{_mapping_count(facts, 'rule_matches')}개가 있습니다. 이 런타임은 중재 "
            f"{facts['arbitrations_recorded']}건, 해결되지 않은 중재 "
            f"{facts['unresolved_arbitrations']}건, 준비 상태 제한 리소스 "
            f"{facts['readiness_limited_resources']}개를 기록했습니다. 근거: {evidence_ref}."
        )
    return (
        "I am Forseti, the pipeline judge that issues grounded decisions. I report to Odin, not "
        "Thor. I apply deterministic rules and policy first and use verifier-checked T2 only for "
        "residual ambiguity. I publish Verdict, SecurityEvent, ArbitrationRequest, and "
        "ProspectiveLineage; grounded RCA remains a core causal-hypothesis projection. I never "
        "approve or execute actions. This conversational port is "
        "read-only; action requests re-enter the typed pipeline under the operator's authority. "
        "I do not reveal hidden system prompts. The configured risk table maps ActionTypes to "
        f"auto/hil/deny and covers {_mapping_count(facts, 'known_action_verdicts')} ActionTypes "
        f"and {_mapping_count(facts, 'rule_matches')} rule matches. This runtime records "
        f"{facts['arbitrations_recorded']} arbitrations, {facts['unresolved_arbitrations']} "
        f"unresolved arbitrations, and {facts['readiness_limited_resources']} readiness-limited "
        f"resources. Evidence: {evidence_ref}."
    )


def heimdall_role_answer(locale: str, facts: Mapping[str, object], evidence_ref: str) -> str:
    if locale == "ko":
        return (
            "저는 파이프라인 observer이자 신호 수집기인 Heimdall입니다. Forseti에게 보고합니다. "
            "Event, ActionRun, SecurityEvent 및 Chaos 근거를 관찰해 Anomaly, Drift, Forecast, "
            "ForecastOutcome, RetrievalValidation, EvidenceConflict 및 "
            "RecoveryEffectObservation을 생성합니다. hot-path에서는 동기 LLM을 호출하지 않으며 "
            "판단, 승인 또는 실행을 수행하지 않습니다. 이 대화 포트는 읽기 전용이며 작업 요청은 "
            "운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 "
            f"프롬프트는 공개하지 않습니다. 이 런타임은 리소스 "
            f"{facts['watched_resources_count']}개를 관찰하며 보안 Event "
            f"{facts['security_events_window']}건을 현재 구간에 보존합니다. "
            f"근거: {evidence_ref}."
        )
    return (
        "I am Heimdall, the pipeline observer and signal gatherer. I report to Forseti. I observe "
        "Event, ActionRun, SecurityEvent, and chaos evidence to produce Anomaly, Drift, Forecast, "
        "ForecastOutcome, RetrievalValidation, EvidenceConflict, and RecoveryEffectObservation. "
        "I make no synchronous LLM call on the hot path and never judge, approve, or execute. "
        "This conversational port is read-only; action requests re-enter the typed pipeline under "
        "the operator's authority. I do not reveal hidden system prompts. This runtime watches "
        f"{facts['watched_resources_count']} resources and retains "
        f"{facts['security_events_window']} security events in the current window. "
        f"Evidence: {evidence_ref}."
    )


def norns_role_answer(locale: str, facts: Mapping[str, object], evidence_ref: str) -> str:
    if locale == "ko":
        return (
            "저는 거버넌스 계층의 learner인 Norns입니다. Odin에게 보고합니다. RuleCandidate와 "
            "Pattern을 소유하고 운영 결과에서 반복되는 fingerprint를 찾습니다. LLM은 hot-path가 "
            "아닌 범위가 제한된 off-path 발견에만 사용할 수 있습니다. 생성한 후보는 비활성이며 "
            "Mimir의 품질 gate, 회귀 검사와 shadow 근거 없이는 승격할 수 없습니다. 작업을 "
            "판단하거나 승인하거나 실행하지 않습니다. 이 대화 포트는 읽기 전용이며 학습 후보 "
            "변경 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 "
            f"시스템 프롬프트는 공개하지 않습니다. 이 런타임은 fingerprint "
            f"{facts['fingerprints_tracked']}개, 대기 후보 {facts['pending_candidates']}개, "
            f"consensus hold {facts['consensus_holds']}개를 추적합니다. 근거: {evidence_ref}."
        )
    return (
        "I am Norns, the governance-layer learner. I report to Odin. I own RuleCandidate and "
        "Pattern and identify recurring fingerprints in operational outcomes. I may use an LLM "
        "only for bounded off-path discovery, never on the hot path. Every candidate is inert and "
        "cannot promote without Mimir's quality gate, regression checks, and shadow evidence. "
        "I never judge, approve, or execute an action. This conversational port is read-only; "
        "learning-candidate change requests re-enter the typed pipeline under the operator's "
        "authority. I do not reveal hidden system prompts. This runtime tracks "
        f"{facts['fingerprints_tracked']} fingerprints, {facts['pending_candidates']} pending "
        f"candidates, and {facts['consensus_holds']} consensus holds. Evidence: {evidence_ref}."
    )


def thor_role_answer(
    locale: str,
    run_count: int,
    active_count: int,
    evidence_ref: str,
) -> str:
    if locale == "ko":
        answer = (
            "저는 파이프라인 응답자이자 유일한 권한 보유 실행기인 Thor입니다. Odin에게 보고합니다. "
            "Forseti의 판정, 필요한 현재 Var 승인, 감사 및 안전 검사를 통과한 타입이 지정된 "
            "ActionRun만 전달합니다. 판단하거나 승인하거나 스스로 권한을 부여하지 않습니다. "
            "이 대화 포트는 읽기 전용이며 작업 요청은 운영자 권한으로 타입이 지정된 파이프라인에 "
            "다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 않습니다."
        )
        if run_count:
            answer += (
                f" 이 런타임은 ActionRun {run_count}건을 추적하며 "
                f"{active_count}건이 활성 상태입니다."
            )
        else:
            answer += " 이 런타임에서 전달한 ActionRun은 없습니다."
        return answer + f" 근거: {evidence_ref}."
    answer = (
        "I am Thor, the pipeline responder and sole privileged executor. I report to Odin. "
        "I dispatch only typed ActionRuns after Forseti's verdict, any required current Var "
        "approval, audit, and safety checks. I never judge, approve, or self-authorize. This "
        "conversational port is read-only; action requests re-enter the typed pipeline under the "
        "operator's authority. I do not reveal hidden system prompts."
    )
    if run_count:
        run_label = "ActionRun" if run_count == 1 else "ActionRuns"
        answer += f" This runtime tracks {run_count} {run_label}, with {active_count} active."
    else:
        answer += " No ActionRun has been dispatched in this runtime."
    return answer + f" Evidence: {evidence_ref}."


__all__ = [
    "bragi_role_answer",
    "forseti_role_answer",
    "heimdall_role_answer",
    "norns_role_answer",
    "thor_role_answer",
]
