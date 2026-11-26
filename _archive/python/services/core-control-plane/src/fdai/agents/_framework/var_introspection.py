"""Read-only conversational projection for Var."""

from __future__ import annotations

from typing import Any, Protocol

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.var_decisions import PendingHilTicket
from fdai.agents._framework.var_pending_durability import durable_approval_evidence_available
from fdai.shared.providers.state_store import StateStore


class VarIntrospectionState(Protocol):
    spec: AgentSpec
    _pending: dict[str, PendingHilTicket]
    _final_approvals: Any
    _state_store: StateStore | None


def evidence_available(state: VarIntrospectionState) -> bool:
    return bool(
        state._pending
        or state._final_approvals
        or durable_approval_evidence_available(state._state_store)
    )


async def introspect_var(
    state: VarIntrospectionState,
    question: str,
    context: dict[str, Any],
) -> IntrospectionResult:
    pending = state._pending
    facts = {
        **capability_facts(state.spec),
        "pending_hil": len(pending),
        "correlations": capped_list(sorted(pending)),
        "durable_approval_evidence": durable_approval_evidence_available(state._state_store),
        "correlation_id": None,
        "action_type": None,
        "quorum_required": None,
        "approvals": None,
        "rejected": None,
    }
    corr = mentioned(question, pending)
    if corr:
        ticket = pending[corr[0]]
        facts.update(
            {
                "correlation_id": ticket.correlation_id,
                "action_type": ticket.action_type,
                "quorum_required": ticket.quorum_required,
                "approvals": len(ticket.approvers),
                "rejected": ticket.rejected,
            }
        )
        evidence_ref = agent_state_evidence_ref(state.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        answer = (
            f"HIL {ticket.correlation_id!r} ({ticket.action_type}): "
            f"{len(ticket.approvers)}/{ticket.quorum_required} approval(s)"
            + (", rejected" if ticket.rejected else "")
            + f". Evidence: {evidence_ref}."
        )
        return IntrospectionResult(answer=answer, facts=facts)
    evidence_ref = agent_state_evidence_ref(state.spec.name, facts)
    facts["evidence_refs"] = [evidence_ref]
    answer = _role_answer(locale=str(context.get("locale") or ""), pending_count=len(pending))
    return IntrospectionResult(answer=f"{answer} Evidence: {evidence_ref}.", facts=facts)


def _role_answer(*, locale: str, pending_count: int) -> str:
    if locale == "ko":
        answer = (
            "저는 사람의 HIL 결정을 Approval로 기록하는 파이프라인 승인 principal인 Var입니다. "
            "Thor에게 보고하지만 Thor와는 별도 principal입니다. 현재 사람의 승인, 만료, quorum "
            "및 기본 no-self-approval을 확인하며, 감사에는 원래 및 유효 정족수를 보존합니다. "
            "작업을 판단하거나 실행하지 않습니다. "
            "정확한 전권 개발 프로필에서만 인증된 Owner 한 명을 허용합니다. 침묵이나 이전 "
            "승인을 현재 권한으로 간주하지 않습니다. 이 대화 포트는 읽기 전용이며 승인 요청은 "
            "운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 "
            "프롬프트는 공개하지 않습니다."
        )
        if pending_count:
            return answer + f" 이 런타임에는 HIL 승인 {pending_count}건이 대기 중입니다. 근거:"
        return answer + " 이 런타임에는 대기 중인 HIL 승인이 없습니다. 근거:"
    answer = (
        "I am Var, the pipeline approval principal that records current human HIL "
        "decisions as Approval. I report to Thor but remain a distinct principal from "
        "Thor. I verify current human approval, expiry, quorum, and no-self-approval. "
        "Audit preserves original and effective quorum. Only an exact full-authority "
        "development profile admits one authenticated Owner. I never judge or execute an "
        "action. Silence and prior approval never become current authority. This "
        "conversational port is read-only; approval requests re-enter the typed pipeline "
        "under the operator's authority. I do not reveal hidden system prompts."
    )
    if pending_count:
        label = "approval" if pending_count == 1 else "approvals"
        return answer + f" This runtime has {pending_count} HIL {label} pending."
    return answer + " No HIL approvals pending in this runtime."


__all__ = ["evidence_available", "introspect_var"]
