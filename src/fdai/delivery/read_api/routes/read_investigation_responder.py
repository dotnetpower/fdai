"""Heimdall conversational adapter for bounded read investigations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.agents import Bragi, Heimdall
from fdai.core.read_investigation import (
    InvestigationExecutionPolicy,
    ReadInvestigationBudget,
    ReadInvestigationExecutionMode,
    ReadInvestigationRequest,
    ReadInvestigationService,
    classify_read_investigation_intent,
    estimate_plan_latency,
    latency_profile,
    plan_read_investigation,
    read_tool_spec,
    resource_name_from_question,
)
from fdai.shared.providers.read_investigation import (
    ReadLatencyProfileStore,
    ResourceSelector,
)


class HeimdallReadInvestigationResponder:
    """Resolve measured-fast reads and hand longer work to the durable route."""

    def __init__(
        self,
        *,
        service: ReadInvestigationService,
        latency_store: ReadLatencyProfileStore,
        scope_ref: str,
        policy: InvestigationExecutionPolicy | None = None,
    ) -> None:
        if not scope_ref.strip() or len(scope_ref) > 256:
            raise ValueError("scope_ref MUST be a bounded identifier")
        self._service = service
        self._latency_store = latency_store
        self._scope_ref = scope_ref
        self._policy = policy or InvestigationExecutionPolicy()

    async def __call__(
        self,
        question: str,
        context: dict[str, object],
    ) -> dict[str, object] | None:
        intent = classify_read_investigation_intent(question)
        resource_name = resource_name_from_question(question)
        if intent is None or resource_name is None:
            return None
        user_id = context.get("user_id")
        session_id = context.get("session_id")
        if not isinstance(user_id, str) or not isinstance(session_id, str):
            return {
                "answer": "Read investigation requires an authenticated user and session.",
                "facts": {"status": "unavailable", "reason": "identity_context_missing"},
            }
        digest = hashlib.sha256(f"{user_id}:{session_id}:{question}".encode()).hexdigest()
        request = ReadInvestigationRequest(
            requester_ref=user_id,
            conversation_ref=session_id,
            correlation_ref=f"read:sha256:{digest}",
            intent=intent,
            selector=ResourceSelector(name=resource_name, scope_ref=self._scope_ref),
            lookback_seconds=3_600,
            requested_evidence=(),
            budget=ReadInvestigationBudget(),
            idempotency_key=f"read:sha256:{digest}",
            created_at=datetime.now(UTC),
        )
        plan = plan_read_investigation(request)
        profiles = {}
        for step in plan.steps:
            spec = read_tool_spec(step.tool_id)
            samples = await self._latency_store.recent(
                tool_id=step.tool_id,
                transport=self._service.transport,
                operation_class=spec.operation_class,
                limit=200,
            )
            profiles[step.tool_id] = latency_profile(samples)
        estimate = estimate_plan_latency(
            plan,
            profiles,
            minimum_samples=self._policy.minimum_profile_samples,
        )
        mode = self._policy.select(plan, estimate)
        if mode is not ReadInvestigationExecutionMode.DIRECT:
            return {
                "answer": (
                    "This investigation requires the durable read-investigation route "
                    f"({mode.value}, estimated upper bound {estimate.upper_ms} ms)."
                ),
                "facts": {
                    "status": "handoff_required",
                    "mode": mode.value,
                    "intent": intent.value,
                    "resource_name": resource_name,
                    "estimated_upper_ms": estimate.upper_ms,
                },
            }
        result = await self._service.execute(plan)
        return {
            "answer": (
                f"Read investigation for {resource_name}: {result.outcome.value}; "
                f"evidence sources={len(result.evidence)}."
            ),
            "facts": {
                "status": result.outcome.value,
                "mode": mode.value,
                "intent": intent.value,
                "resource_name": resource_name,
                "evidence_refs": result.evidence_refs,
                "evidence_sources": tuple(item.authority for item in result.evidence),
            },
        }


class HeimdallReadInvestigationChatDelegate:
    """Expose only supported read investigations to Command Deck evidence enrichment."""

    def __init__(self, *, responder: HeimdallReadInvestigationResponder) -> None:
        self._bragi = Bragi()
        heimdall = Heimdall(read_investigation_hook=responder)
        self._bragi.register_responder("Heimdall", heimdall.on_conversation_turn)

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, object] | None:
        if classify_read_investigation_intent(prompt) is None:
            return None
        scoped_session = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
        turn = await self._bragi.ask(
            session_id=f"read:sha256:{scoped_session}",
            user_id=user_id,
            question=prompt,
            allow_action_proposal=False,
        )
        if turn is None or turn.primary_agent != "Heimdall":
            return None
        answer = turn.answer.get("answer")
        facts = turn.answer.get("facts")
        if not isinstance(answer, str) or not isinstance(facts, dict):
            return None
        return {
            "primary_agent": "Heimdall",
            "answer": answer,
            "facts": facts,
            "contributors": [],
            "contributor_answers": [],
            "trace_ref": str(turn.answer.get("trace_ref") or "read-investigation")[:256],
        }


__all__ = [
    "HeimdallReadInvestigationChatDelegate",
    "HeimdallReadInvestigationResponder",
]
