"""Operator ask orchestration mixin for Bragi."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
)

from fdai.agents._framework.bragi_constants import (
    _CONTRIBUTOR_TIMEOUT_SECONDS,
    _MAX_CONTRIBUTORS,
    _MAX_SESSIONS,
    _SESSION_INACTIVITY_LIMIT,
)
from fdai.agents._framework.bragi_contributors import (
    AnswerFn,
    ask_contributors,
    evidence_conflicts,
    normalize_responder_answer,
)
from fdai.agents._framework.bragi_diagnostics import attach_pantheon_diagnostics
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import evict_oldest
from fdai.agents._framework.bragi_runtime_helpers import (
    _append_turn,
    _principal_scope,
    _prior_turns_ref,
    _resource_type_from_proposal,
    _session_ref,
    _validate_question,
    _validate_tool_answer_envelope,
)

if TYPE_CHECKING:
    from fdai.agents.bragi import ToolAnswerFn

_LOG = logging.getLogger("fdai.agents.bragi")


class BragiAskRuntimeMixin:
    """Handle one bounded operator question."""

    _session_locks: dict[str, asyncio.Lock]
    _clock: Callable[[], datetime]
    _sessions: dict[str, ConversationSession]
    _tool_answer: ToolAnswerFn | None
    _agent_responders: dict[str, AnswerFn]

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        async def _reserve_turn_index(
            self,
            session_id: str,
            session: ConversationSession,
        ) -> int: ...

        async def _publish_conversation(
            self,
            session: ConversationSession,
            *,
            status: str = "active",
        ) -> bool: ...

        async def _judge_async(
            self,
            question: str,
            *,
            context: tuple[str, ...],
        ) -> tuple[Any | None, str]: ...

        async def submit_action_proposal(
            self,
            *,
            session_id: str,
            user_id: str,
            question: str,
            judgment: SemanticJudgmentProposal,
            initiator_role: str | None = None,
        ) -> dict[str, Any]: ...

        async def _checkpoint_turn_payload(
            self,
            *,
            session: ConversationSession,
            turn: Turn,
        ) -> dict[str, Any]: ...

        async def _publish_turn(self, payload: dict[str, Any]) -> None: ...

        def route(
            self,
            judgment: SemanticJudgmentProposal,
            *,
            question: str | None = None,
        ) -> RoutingDecision: ...

        async def _call_responder(
            self,
            agent_name: str,
            question: str,
            context: dict[str, Any],
        ) -> tuple[dict[str, Any] | None, str | None]: ...

        async def _publish_handoff(
            self,
            *,
            session_id: str,
            question: str,
            turn_index: int,
            intent_category: str,
            resource_type: str,
            primary_agent: str,
            failure_reason_code: str,
        ) -> str: ...

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        locale: str = "en",
        initiator_role: str | None = None,
        allow_action_proposal: bool = False,
        materialize_handoff: bool = False,
    ) -> Turn:
        """Route + call primary + record the turn.

        ``locale`` selects the language layer. ``initiator_role`` (the console session's Entra role)
        is applied by the
        entry RBAC gate when the turn is an action command; ``None`` skips it.
        A read-only channel sets ``allow_action_proposal=False`` so an action
        utterance is redirected to the dedicated proposal route without
        publishing anything from the conversational port.
        """
        _validate_question(question)
        session_lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        ended_session: ConversationSession | None = None
        async with session_lock:
            now = self._clock()
            session = self._sessions.setdefault(
                session_id,
                ConversationSession(
                    session_id=session_id,
                    user_id=user_id,
                    created_at=now,
                    last_active_at=now,
                ),
            )
            if session.user_id != user_id:
                raise PermissionError(f"session {session_id!r} belongs to a different user")
            last_active = session.last_active_at or session.created_at or now
            if session.turns and now - last_active >= _SESSION_INACTIVITY_LIMIT:
                session.ended_at = last_active + _SESSION_INACTIVITY_LIMIT
                ended_session = session
                session = ConversationSession(
                    session_id=session_id,
                    user_id=user_id,
                    created_at=now,
                    last_active_at=now,
                    generation=ended_session.generation + 1,
                )
                self._sessions[session_id] = session
                self.record_behavior("session:expired")
            publish_conversation = (
                not session.conversation_published and not session.conversation_publication_inflight
            )
            if publish_conversation:
                session.conversation_publication_inflight = True
            turn_index = await self._reserve_turn_index(session_id, session)
            prior_turns_ref = _prior_turns_ref(session)
            semantic_context = (prior_turns_ref,) if prior_turns_ref else ()
            session.last_active_at = now
            # Bound the session map so a long-lived narrator cannot leak one entry
            # per session id forever (evicts oldest, never the active session).
            evict_oldest(self._sessions, _MAX_SESSIONS, keep=session_id)
            evict_oldest(self._session_locks, _MAX_SESSIONS, keep=session_id)
        if ended_session is not None:
            await self._publish_conversation(ended_session, status="ended")
        if publish_conversation:
            try:
                conversation_published = await self._publish_conversation(session)
            finally:
                async with session_lock:
                    session.conversation_publication_inflight = False
            if conversation_published:
                async with session_lock:
                    session.conversation_published = True
        judgment_result, judgment_status = await self._judge_async(
            question, context=semantic_context
        )
        judgment = (
            judgment_result.proposal
            if judgment_result is not None and judgment_result.accepted
            else None
        )
        # MUST-NOT-bypass (agent-pantheon.md 7.7): a command ("restart vm-1")
        # is not answered by the conversational port. Bragi translates it into
        # a typed ActionProposal whose initiator is the operator and hands it
        # to the pipeline (Huginn -> Forseti judge -> Var approve -> Thor
        # execute). Bragi never calls an executor; it only submits + renders.
        if judgment is not None and judgment.action_posture == "draft_only":
            if allow_action_proposal:
                result = await self.submit_action_proposal(
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
                    judgment=judgment,
                    initiator_role=initiator_role,
                )
            else:
                result = {
                    "submitted": False,
                    "abstain_reason": "action_route_required",
                }
            answer: dict[str, Any] = {
                "answer": None,
                "primary_agent": None,
                "requires_typed_pipeline": True,
                **result,
            }
            attach_pantheon_diagnostics(
                answer=answer,
                decision=RoutingDecision(
                    primary_agent=None,
                    scores={},
                    tie_break=None,
                    method="typed_action_reentry",
                ),
                question=question,
                session_id=session_id,
            )
            turn = Turn(
                turn_index=turn_index,
                question=question,
                primary_agent=None,
                answer=answer,
                decision=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            )
            turn_payload = await self._checkpoint_turn_payload(session=session, turn=turn)
            async with session_lock:
                _append_turn(session, turn)
            await self._publish_turn(turn_payload)
            return turn
        decision = (
            self.route(judgment, question=question)
            if judgment is not None
            else RoutingDecision(
                primary_agent=None,
                scores={},
                tie_break=None,
                method="semantic_unavailable",
                provider_status=(
                    judgment_result.receipt.disposition.value
                    if judgment_result is not None
                    else judgment_status
                ),
            )
        )
        if judgment is None or decision.primary_agent is None:
            clarification = (
                judgment_result.proposal.clarification
                if judgment_result is not None
                and judgment_result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION
                and judgment_result.proposal is not None
                else None
            )
            answer = {
                "answer": clarification,
                "primary_agent": None,
                "abstain_reason": (
                    "semantic_clarification_required" if clarification else "semantic_unavailable"
                ),
                "handoff_needed": True,
                "routing_provider_status": decision.provider_status,
            }
        else:
            tool_answer = (
                await self._tool_answer(decision.primary_agent, question, session_id)
                if self._tool_answer is not None
                else None
            )
            if tool_answer is None:
                normalized_answer, response_error = await self._call_responder(
                    decision.primary_agent,
                    question,
                    {
                        "session_ref": _session_ref(session_id, session.generation),
                        "principal_scope": _principal_scope(user_id),
                        "locale": locale,
                        **({"prior_turns_ref": prior_turns_ref} if prior_turns_ref else {}),
                        "semantic_action_posture": judgment.action_posture,
                        "semantic_requested_facets": judgment.requested_facets,
                        "semantic_primary_intent": judgment.primary_intent,
                        "semantic_targets": tuple(
                            target.model_dump(mode="json") for target in judgment.targets
                        ),
                    },
                )
            else:
                tool_error = _validate_tool_answer_envelope(decision.primary_agent, tool_answer)
                normalized_answer, response_error = (
                    normalize_responder_answer(
                        decision.primary_agent,
                        tool_answer,
                    )
                    if tool_error is None
                    else (None, tool_error)
                )
                if normalized_answer is not None:
                    normalized_answer["conversation_tools"] = list(
                        tool_answer.get("conversation_tools", [])
                    )
                    plan = tool_answer.get("conversation_tool_plan")
                    if isinstance(plan, dict):
                        normalized_answer["conversation_tool_plan"] = dict(plan)
                    results = tool_answer.get("conversation_tool_results")
                    if isinstance(results, list):
                        normalized_answer["conversation_tool_results"] = [
                            dict(item) for item in results if isinstance(item, dict)
                        ]
            if normalized_answer is None:
                answer = {
                    "answer": None,
                    "facts": {},
                    "primary_agent": decision.primary_agent,
                    "abstain_reason": response_error or "response_invalid",
                    "handoff_needed": True,
                }
                if tool_answer is not None:
                    results = tool_answer.get("conversation_tool_results")
                    if isinstance(results, list):
                        answer["conversation_tool_results"] = [
                            dict(item) for item in results if isinstance(item, dict)
                        ]
                    plan = tool_answer.get("conversation_tool_plan")
                    if isinstance(plan, dict):
                        answer["conversation_tool_plan"] = dict(plan)
                    tools = tool_answer.get("conversation_tools")
                    if isinstance(tools, list):
                        answer["conversation_tools"] = list(tools)
            else:
                answer = normalized_answer
                if not isinstance(answer.get("answer"), str):
                    answer["handoff_needed"] = True
                    contributor_answers: list[dict[str, Any]] = []
                    contributor_errors: list[str] = []
                else:
                    contributor_answers, contributor_errors = await ask_contributors(
                        self._agent_responders,
                        decision.contributors,
                        question=question,
                        session_id=session_id,
                        limit=_MAX_CONTRIBUTORS,
                        timeout_seconds=_CONTRIBUTOR_TIMEOUT_SECONDS,
                        logger=_LOG,
                        primary_agent=decision.primary_agent,
                        locale=locale,
                    )
                successful = [item["agent"] for item in contributor_answers]
                answer["contributors"] = successful
                answer["contributor_answers"] = contributor_answers
                if contributor_errors:
                    answer["contributor_errors"] = contributor_errors
                primary_text = answer.get("answer")
                conflicts = evidence_conflicts(
                    decision.primary_agent,
                    answer,
                    contributor_answers,
                )
                if conflicts:
                    answer["answer"] = None
                    answer["abstain_reason"] = "agent_evidence_conflict"
                    answer["handoff_needed"] = True
                    answer["unresolved_conflicts"] = conflicts
                elif isinstance(primary_text, str) and contributor_answers:
                    lines = [f"{decision.primary_agent}: {primary_text}"]
                    lines.extend(
                        f"{item['agent']}: {item['answer']}"
                        for item in contributor_answers
                        if isinstance(item.get("answer"), str)
                    )
                    answer["answer"] = "\n".join(lines)
                answer["score_breakdown"] = decision.scores
                answer["tie_break_reason"] = decision.tie_break
                answer["routing_method"] = decision.method
                answer["semantic_score"] = decision.semantic_score
                answer["semantic_margin"] = decision.semantic_margin
                answer["routing_provider_status"] = decision.provider_status
        if judgment_result is not None:
            answer["semantic_judgment"] = {
                "receipt_digest": judgment_result.receipt.receipt_digest,
                "input_digest": judgment_result.receipt.input_digest,
                "profile_id": judgment_result.receipt.profile_id,
                "profile_version": judgment_result.receipt.profile_version,
                "tier": (
                    judgment_result.receipt.tier.value
                    if judgment_result.receipt.tier is not None
                    else None
                ),
                "model_config_digest": judgment_result.receipt.model_config_digest,
                "prompt_digest": judgment_result.receipt.prompt_digest,
                "confidence": judgment_result.receipt.confidence,
                "ambiguous": judgment_result.receipt.ambiguous,
                "latency_ms": judgment_result.receipt.latency_ms,
                "disposition": judgment_result.receipt.disposition.value,
                "reason_code": judgment_result.receipt.reason_code,
                **(
                    {"model_identity": judgment_result.observations[-1].model}
                    if judgment_result.observations
                    else {}
                ),
                "execution_authority": False,
            }
        attach_pantheon_diagnostics(
            answer=answer,
            decision=decision,
            question=question,
            session_id=session_id,
        )
        if answer.get("handoff_needed") and materialize_handoff:
            answer["handoff_status"] = await self._publish_handoff(
                session_id=session_id,
                question=question,
                turn_index=turn_index,
                intent_category=(judgment.primary_intent if judgment is not None else "unknown"),
                resource_type=_resource_type_from_proposal(judgment),
                primary_agent=decision.primary_agent or "unassigned",
                failure_reason_code=str(answer.get("abstain_reason") or "no_route"),
            )
        turn = Turn(
            turn_index=turn_index,
            question=question,
            primary_agent=decision.primary_agent,
            answer=answer,
            decision=decision,
        )
        turn_payload = await self._checkpoint_turn_payload(session=session, turn=turn)
        async with session_lock:
            _append_turn(session, turn)
        await self._publish_turn(turn_payload)
        return turn
