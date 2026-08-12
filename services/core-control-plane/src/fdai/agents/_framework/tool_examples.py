"""How an operator actually asks for each owned read tool.

A tool declares what it yields - an id, a purpose, and fact keys - which
is enough for a machine and not enough for a person. Operators do not ask
"read cost samples"; they ask why the bill went up. Matching a question
against the declaration alone selected the right tool for 3 of 14
realistic questions, and an embedding over those same declarations scored
exactly the same, because a declaration sits in a different register from
a question. Pairing each tool with the way its question is really asked
raised that to 14 of 14 in the top three.

The examples are bilingual for the same reason the agents' routing
examples are: an operator asks in either language, and a tool that only
recognises English questions gives Korean operators a quietly weaker read
path. They live here rather than beside the declarations because
``pantheon.py`` is near its size ceiling - the same reason the role
directives live in ``charters.py``.

These are retrieval anchors, not documentation and not evidence. They
never reach an answer; they only help decide which owned tool a question
is about.
"""

from __future__ import annotations

from typing import Final

#: ``tool_id`` -> (English question, Korean question).
#:
#: Every declared tool MUST appear exactly once. A tool with no example is
#: unreachable by the way anyone actually asks for it, and a key with no
#: tool is an anchor pulling questions toward something that does not
#: exist. Both are gated by the tool planner tests.
TOOL_EXAMPLES: Final[dict[str, tuple[str, str]]] = {
    # Odin - portfolio arbitration
    "read_arbitration_history": (
        "Which priority conflicts were arbitrated before, and how did they end?",
        "예전에 우선순위 충돌을 어떻게 조정했었지?",
    ),
    "read_portfolio_policy": (
        "What decides which domain wins when goals conflict?",
        "목표가 충돌하면 뭘 기준으로 우선순위를 정해?",
    ),
    "read_arbitration_decision": (
        "Which domain won the last conflict and by how much?",
        "지난번 충돌은 어느 쪽이 이겼고 차이가 얼마였어?",
    ),
    "read_portfolio_outcomes": (
        "How did the decisions across the portfolio turn out?",
        "전체적으로 결정들이 어떻게 끝났어?",
    ),
    # Thor - execution
    "read_action_runs": (
        "What is running right now, and did anything finish or fail?",
        "지금 뭐 돌고 있어? 끝난 거나 실패한 거 있어?",
    ),
    "read_execution_history": (
        "What limits are in place before we execute a change?",
        "변경 실행 전에 어떤 제한이 걸려 있어?",
    ),
    # Forseti - judgment
    "read_verdicts": (
        "Was that change judged safe or risky?",
        "그 변경 안전하다고 나왔어 위험하다고 나왔어?",
    ),
    "read_judgment_context": (
        "Which rules and conflicts were considered when judging this?",
        "이거 판단할 때 어떤 규칙이랑 충돌을 봤어?",
    ),
    "read_rca_evidence": (
        "What actually broke, and what caused the incident?",
        "장애 원인이 뭐야? 뭐가 터진 거야?",
    ),
    # Huginn - ingress
    "read_ingress_health": (
        "Are events still arriving, and how many came in?",
        "이벤트 들어오고 있어? 얼마나 들어왔어?",
    ),
    "read_dedup_status": (
        "Are we collapsing duplicate alerts properly?",
        "중복 알림 잘 합쳐지고 있어?",
    ),
    # Heimdall - observation
    "read_observations": (
        "What did we notice on the resources before this happened?",
        "이 일 생기기 전에 리소스에서 뭐 잡힌 거 있어?",
    ),
    "read_security_window": (
        "Has anything suspicious shown up recently?",
        "최근에 수상한 거 있었어?",
    ),
    "read_forecast_status": (
        "What did the forecast say would happen?",
        "예측에서는 뭐가 일어난다고 했어?",
    ),
    "read_drift_status": (
        "Did anything drift away from its intended configuration?",
        "설정이 원래대로랑 달라진 거 있어?",
    ),
    # Vidar - recovery
    "read_rollback_history": (
        "What did we undo, and when did we roll something back?",
        "어제 되돌린 작업 뭐였지? 롤백 이력은 언제 생겼어?",
    ),
    "read_recovery_safety": (
        "Is it safe to recover this, or does something depend on it?",
        "이거 복구해도 안전해? 딸린 게 있어?",
    ),
    # Var - approval
    "read_pending_approvals": (
        "Who still has to sign off, and what is waiting on them?",
        "지금 누가 결재 기다리고 있어? 승인 대기 뭐 있어?",
    ),
    "read_approval_policy": (
        "Who is allowed to approve this, and can the same person do both?",
        "누가 승인할 수 있어? 같은 사람이 둘 다 해도 돼?",
    ),
    # Bragi - narration and routing
    "list_agent_capabilities": (
        "Which agents exist and what does each one handle?",
        "에이전트 뭐뭐 있고 각각 뭘 담당해?",
    ),
    "read_routing_policy": (
        "How is a question routed to the right owner?",
        "질문이 어떻게 담당자한테 배정돼?",
    ),
    # Saga - audit
    "read_audit_chain": (
        "Is there a tamper-evident record of what happened?",
        "무슨 일이 있었는지 위변조 못 하는 기록이 있어?",
    ),
    "read_issue_handoffs": (
        "Which issues were handed over, and to whom?",
        "어떤 이슈가 누구한테 넘어갔어?",
    ),
    # Mimir - rule governance
    "read_rule_catalog": (
        "Which rules are active, and which are switched off?",
        "지금 켜져 있는 규칙 뭐야? 꺼진 건?",
    ),
    "read_candidate_queue": (
        "What new rules are waiting to be promoted?",
        "새로 올라갈 규칙 대기 중인 거 있어?",
    ),
    "read_policy_history": (
        "How did this policy change over time?",
        "이 정책이 어떻게 바뀌어 왔어?",
    ),
    # Muninn - memory
    "read_state_context": (
        "What state and context do we have stored?",
        "저장된 상태랑 컨텍스트 뭐가 있어?",
    ),
    "read_case_history": (
        "Can we look up what happened in past cases?",
        "과거 사례 찾아볼 수 있어?",
    ),
    # Norns - patterns
    "read_pattern_observations": (
        "Is this problem recurring, and have we seen the pattern before?",
        "이 문제 반복되는 거야? 전에도 이런 패턴 있었어?",
    ),
    "read_candidate_holds": (
        "What is being held back and not promoted yet?",
        "아직 승격 안 되고 잡혀 있는 거 뭐야?",
    ),
    # Njord - cost
    "read_cost_samples": (
        "How much are we spending, and why did the bill go up?",
        "우리 비용이 얼마나 들고 있어? 이번달 청구서 왜 이렇게 나왔지?",
    ),
    "read_cost_model": (
        "What does each action cost us?",
        "각 작업의 비용은 얼마나 드는지 보여줘?",
    ),
    "read_budget_status": (
        "Are we within budget, or about to blow through it?",
        "예산 안에 있어? 비용이 예산을 넘을 것 같아?",
    ),
    # Freyr - capacity
    "read_capacity_forecasts": (
        "Are we running out of headroom, and will capacity hold?",
        "용량 부족해질까? 여유 남아 있어?",
    ),
    "read_sizing_recommendations": (
        "Should we scale this up or down?",
        "리소스 더 키워야 하나 줄여야 하나?",
    ),
    # Loki - resilience
    "read_chaos_experiments": (
        "What resilience experiments are proposed or running?",
        "지금 돌고 있는 실험 있어? 제안된 실험 뭐야?",
    ),
    "read_chaos_safety": (
        "How far can an experiment reach before it is unsafe?",
        "실험이 어디까지 영향 줄 수 있어? 위험 범위가 어디야?",
    ),
    "read_resilience_scores": (
        "How resilient did we score, and did it improve?",
        "복원력 점수 어때? 나아졌어?",
    ),
}


def tool_examples(tool_id: str) -> tuple[str, ...]:
    """Return the bilingual questions that anchor ``tool_id``."""
    pair = TOOL_EXAMPLES.get(tool_id)
    return pair if pair is not None else ()


__all__ = ["TOOL_EXAMPLES", "tool_examples"]
