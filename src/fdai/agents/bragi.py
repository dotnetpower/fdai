"""Bragi - Narrator (Wave 4 behavior).

Bragi is the operator conversational port. It routes NL queries to a
primary agent using a deterministic scoring model built on
:pyattr:`AgentSpec.question_domains`, aggregates typed responses, and
renders a natural-language answer.

Wave 4 keeps the LLM off the hot path: routing is T0 keyword + T1
embedding-similarity (with the T1 similarity implementation stubbed
deterministically until an embedding provider lands). The T2 LLM
fallback for intent classification and the multi-turn context window
integrate with the seams here but are exercised only in the
conversational-port smoke tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bragi_contributors import (
    AnswerFn,
    ask_contributors,
    evidence_conflicts,
    normalize_responder_answer,
)
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import append_submitted, evict_oldest, record_progress
from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bragi_routing import route_question, translate_action_intent
from fdai.agents._framework.deliberation import (
    ConversationDeliberator,
    EscalationBudget,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    is_action_intent,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.semantic_routing import SemanticAgentRouter

_LOG = logging.getLogger(__name__)

#: A proposal sink accepts one raw operator ActionProposal and hands it to the
#: typed pipeline (the composition root wires this to ``Huginn.ingest`` - the
#: sole writer of ``object.event``). Returns the normalized event payload, or
#: ``None`` when the collector deduplicated it. Bragi NEVER calls an executor
#: (agent-pantheon.md 7.7); it only submits through this sink.
ProposalSink = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

#: Deterministic verb -> ActionType mapping for operator conversational
#: requests (Wave 4, LLM-free). The verb is the leading imperative token that
#: :func:`~fdai.agents.introspection.is_action_intent` already recognised; a
#: verb with no mapping abstains rather than guessing an action.
#: Bounds on operator-supplied values that ride into a proposal, and on the
#: in-memory maps a long-lived Bragi accumulates, so a conversational port that
#: runs for weeks cannot leak one entry per session / correlation forever or let
#: one large value bloat the pipeline + audit.
_MAX_SESSIONS = 1_000
_MAX_SESSION_TURNS = 100
_MAX_QUESTION_CHARS = 2_000
_MAX_PROGRESS_KEYS = 5_000
#: Cap on progress steps retained per correlation. A pipeline has a handful of
#: lifecycle states, but at-least-once redelivery (or a chatty retry) could
#: append without limit, so the per-correlation list is bounded too - not just
#: the key count.
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 3
_CONTRIBUTOR_TIMEOUT_SECONDS = 2.0
_RESPONDER_TIMEOUT_SECONDS = 2.0
_PROPOSAL_TIMEOUT_SECONDS = 5.0

_CURRENT_SCREEN_DATA_INTENT = re.compile(
    r"\b(?:how many|count|share|rate|eps|attention|failed|mode|terminal\s+stage|"
    r"affected|cpu\s+usage|approved|owner|region|monthly\s+cost|latest|recent|logged|"
    r"top|most\s+common|common\s+action|promot\w*|ready|t0|t1|t2)\b"
    r"|몇\s*개|개수|비율|주의|실패|모드|최종\s*단계|영향|사용률|승인|소유자|리전|"
    r"월\s*비용|최근|가장\s*흔한\s*액션|준비|승격|그럼\s*T[012]",
    re.IGNORECASE,
)


#: Entry RBAC gate for execute-class conversational requests. A console
#: session's Entra role is mapped to the canonical capability matrix
#: (:mod:`fdai.core.rbac.roles`) and MUST carry ``AUTHOR_DRAFT_PR`` to submit an
#: action - the SAME capability the HTTP console-action route requires, so the
#: two entry surfaces never drift. In particular ``BreakGlass`` is hard-isolated
#: (NOT a superset of Owner) and does NOT carry ``AUTHOR_DRAFT_PR``, so it cannot
#: submit a normal action from either surface. Refused before the proposal
#: enters the pipeline (defense-in-depth with Forseti's principal-level RBAC
#: deny).
class Bragi(Agent):
    """Wave-4 Bragi: routing + orchestration + session tracker."""

    def __init__(
        self,
        *,
        semantic_router: SemanticAgentRouter | None = None,
        t2_synthesizer: T2ConversationSynthesizer | None = None,
        escalation_budget: EscalationBudget | None = None,
        responder_timeout_seconds: float = _RESPONDER_TIMEOUT_SECONDS,
        proposal_timeout_seconds: float = _PROPOSAL_TIMEOUT_SECONDS,
    ) -> None:
        if responder_timeout_seconds <= 0:
            raise ValueError("responder timeout MUST be positive")
        if proposal_timeout_seconds <= 0:
            raise ValueError("proposal timeout MUST be positive")
        super().__init__(spec=_BRAGI)
        self._sessions: dict[str, ConversationSession] = {}
        self._agent_responders: dict[str, AnswerFn] = {}
        self._proposal_sink: ProposalSink | None = None
        self._semantic_router = semantic_router
        self._responder_timeout_seconds = responder_timeout_seconds
        self._proposal_timeout_seconds = proposal_timeout_seconds
        self._deliberator = ConversationDeliberator(
            specs=PANTHEON_SPECS,
            semantic_router=semantic_router,
            t2_synthesizer=t2_synthesizer,
            call_responder=self._call_responder,
            escalation_budget=escalation_budget,
        )
        # Per-correlation pipeline progress, appended as verdict / action-run
        # states arrive on the typed port, so an operator can be told where
        # their submitted action is (submitted -> verdicted -> hil_pending ->
        # executing -> succeeded / denied). Bounded both ways: the key count
        # by _evict_oldest (_MAX_PROGRESS_KEYS) and each list's length by
        # _MAX_PROGRESS_STEPS, with redelivered steps deduped.
        self._progress: dict[str, list[dict[str, Any]]] = {}

    # ---- registration --------------------------------------------------

    def register_responder(self, agent_name: str, fn: AnswerFn) -> None:
        if agent_name not in PANTHEON_NAMES:
            raise ValueError(f"unknown responder agent: {agent_name!r}")
        if agent_name in self._agent_responders:
            raise ValueError(f"responder already registered: {agent_name!r}")
        self._agent_responders[agent_name] = fn

    def register_proposal_sink(self, fn: ProposalSink) -> None:
        """Wire the typed-pipeline entry (composition root binds Huginn.ingest).

        Without a sink, an action request falls back to the
        ``requires_typed_pipeline`` signal (no pipeline available) so behavior
        is unchanged where the pantheon is not wired.
        """
        self._proposal_sink = fn

    async def _call_responder(
        self,
        agent_name: str,
        question: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        responder = self._agent_responders.get(agent_name)
        if responder is None:
            return None, "responder_not_registered"
        try:
            raw_response = await asyncio.wait_for(
                responder(question, context),
                timeout=self._responder_timeout_seconds,
            )
        except TimeoutError:
            _LOG.warning("bragi_responder_timeout", extra={"agent": agent_name})
            return None, "timeout"
        except Exception as exc:  # noqa: BLE001 - isolate one primary responder
            _LOG.warning(
                "bragi_responder_failed",
                extra={"agent": agent_name, "error_type": type(exc).__name__},
            )
            return None, "responder_error"
        return normalize_responder_answer(agent_name, raw_response)

    # ---- action proposal (conversational-port re-entry, 7.7) -----------

    async def submit_action_proposal(
        self, *, session_id: str, user_id: str, question: str, initiator_role: str | None = None
    ) -> dict[str, Any]:
        """Translate an operator command into a typed ActionProposal.

        Builds a proposal whose ``initiator_principal`` is the operator (never
        Bragi), names the ActionType the leading verb maps to, and hands it to
        the typed pipeline through the wired sink (Huginn -> Forseti -> Var ->
        Thor). Returns a status envelope with the ``correlation_id`` the
        operator can track; it NEVER executes the action itself.

        When ``initiator_role`` is supplied (the console session's Entra role),
        an entry RBAC gate refuses a request below the execute floor
        (``Contributor``) before the proposal enters the pipeline - so a Reader
        cannot submit any action. ``None`` skips the entry gate (a
        pantheon-internal caller with no console role); Forseti's principal RBAC
        still applies downstream.
        """
        proposal, status = build_action_proposal(
            session_id=session_id,
            user_id=user_id,
            question=question,
            initiator_role=initiator_role,
            pipeline_available=self._proposal_sink is not None,
        )
        if proposal is None or self._proposal_sink is None:
            return status
        try:
            await asyncio.wait_for(
                self._proposal_sink(proposal),
                timeout=self._proposal_timeout_seconds,
            )
        except TimeoutError:
            _LOG.warning("bragi_proposal_timeout", extra={"action_type": status["action_type"]})
            return {**status, "submitted": False, "abstain_reason": "proposal_timeout"}
        except Exception as exc:  # noqa: BLE001 - isolate typed-pipeline handoff
            _LOG.warning(
                "bragi_proposal_failed",
                extra={
                    "action_type": status["action_type"],
                    "error_type": type(exc).__name__,
                },
            )
            return {**status, "submitted": False, "abstain_reason": "proposal_sink_error"}
        correlation_id = str(status["correlation_id"])
        action_type = str(status["action_type"])
        append_submitted(
            self._progress,
            correlation_id,
            action_type,
            max_keys=_MAX_PROGRESS_KEYS,
        )
        return status

    # ---- typed port (progress rendering) -------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Record pipeline progress for a submitted proposal.

        Bragi subscribes to ``object.verdict`` and ``object.action-run`` only
        to render progress back to the operator (agent-pantheon.md 7.7 - Bragi
        renders, never executes). It appends the state; it publishes nothing.
        """
        record_progress(
            self._progress,
            topic,
            payload,
            max_keys=_MAX_PROGRESS_KEYS,
            max_steps=_MAX_PROGRESS_STEPS,
        )
        return None

    def progress_for(self, correlation_id: str) -> list[dict[str, Any]]:
        """The recorded pipeline progress for one submitted proposal."""
        return list(self._progress.get(correlation_id, []))

    # ---- agent-to-agent introspection ----------------------------------

    async def introspect_agent(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Agent-to-agent (A2A) NL introspection (agent-pantheon.md 6.2).

        A pantheon agent (``requester``) asks another agent a
        natural-language question through Bragi - the same conversational
        port operators use - when the typed schema is not a fit (e.g. Odin
        asking Saga "who executed correlation abc"). The request is
        read-only: each agent's conversational port refuses a command and
        signals it must re-enter the typed pipeline (7.7), so A2A can never
        become a side-channel that bypasses judge/approve/execute.

        The shared correlation trace (``context['correlation_id']``) is the
        only thing the two ports share; the response carries ``requester``
        so the audit trail shows which agent asked.
        """
        _validate_question(question)
        if requester not in PANTHEON_NAMES:
            # A2A is pantheon-internal: an unknown requester would poison the
            # audit trail (spoofed "who asked"). Reject at the boundary.
            raise ValueError(f"unknown requester agent: {requester!r}")
        if agent_name not in PANTHEON_NAMES:
            raise ValueError(f"unknown target agent: {agent_name!r}")
        ctx: dict[str, Any] = {"requester": requester, "a2a": True}
        correlation_id = (context or {}).get("correlation_id")
        if isinstance(correlation_id, str) and 0 < len(correlation_id) <= 256:
            ctx["correlation_id"] = correlation_id
        normalized, response_error = await self._call_responder(
            agent_name,
            question,
            ctx,
        )
        trace_ref = str(ctx.get("correlation_id") or "")
        response = (
            normalized
            if normalized is not None
            else {
                "primary_agent": agent_name,
                "answer": None,
                "facts": {},
                "abstain_reason": response_error or "response_invalid",
            }
        )
        response["requester"] = requester
        response["trace_ref"] = trace_ref
        await self._publish_a2a_turn(
            requester=requester,
            target_agent=agent_name,
            question=question,
            response=response,
        )
        return response

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """Delegate one bounded read-only discussion to the framework orchestrator."""
        return await self._deliberator.deliberate(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
        )

    # ---- routing -------------------------------------------------------

    def route(self, question: str) -> RoutingDecision:
        return route_question(question, max_contributors=_MAX_CONTRIBUTORS)

    async def route_with_semantic_fallback(self, question: str) -> RoutingDecision:
        t0 = self.route(question)
        if self._semantic_router is None:
            return t0
        return await self._semantic_router.route(
            question,
            t0=t0,
            max_contributors=_MAX_CONTRIBUTORS,
        )

    def should_delegate(self, question: str, view_context: dict[str, Any]) -> bool:
        """Return whether a question needs agent-owned state beyond the screen."""
        route_id = str(view_context.get("routeId") or "").strip()
        has_screen_snapshot = "facts" in view_context or "records" in view_context
        if not route_id or not has_screen_snapshot:
            return True
        return _CURRENT_SCREEN_DATA_INTENT.search(question) is None

    # ---- session -------------------------------------------------------

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        initiator_role: str | None = None,
        allow_action_proposal: bool = True,
        materialize_handoff: bool = True,
    ) -> Turn:
        """Route + call primary + record the turn.

        ``initiator_role`` (the console session's Entra role) is applied by the
        entry RBAC gate when the turn is an action command; ``None`` skips it.
        A read-only channel sets ``allow_action_proposal=False`` so an action
        utterance is redirected to the dedicated proposal route without
        publishing anything from the conversational port.
        """
        _validate_question(question)
        session = self._sessions.setdefault(
            session_id,
            ConversationSession(session_id=session_id, user_id=user_id),
        )
        if session.user_id != user_id:
            raise PermissionError(f"session {session_id!r} belongs to a different user")
        # Bound the session map so a long-lived narrator cannot leak one entry
        # per session id forever (evicts oldest, never the active session).
        evict_oldest(self._sessions, _MAX_SESSIONS, keep=session_id)
        # MUST-NOT-bypass (agent-pantheon.md 7.7): a command ("restart vm-1")
        # is not answered by the conversational port. Bragi translates it into
        # a typed ActionProposal whose initiator is the operator and hands it
        # to the pipeline (Huginn -> Forseti judge -> Var approve -> Thor
        # execute). Bragi never calls an executor; it only submits + renders.
        if is_action_intent(question):
            if allow_action_proposal:
                result = await self.submit_action_proposal(
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
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
            turn = Turn(
                turn_index=_next_turn_index(session),
                question=question,
                primary_agent=None,
                answer=answer,
                decision=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            )
            _append_turn(session, turn)
            await self._publish_turn(session_id=session_id, turn=turn)
            return turn
        decision = await self.route_with_semantic_fallback(question)
        if decision.primary_agent is None:
            answer = {
                "answer": None,
                "primary_agent": None,
                "abstain_reason": "no_route",
                "handoff_needed": True,
            }
        else:
            normalized_answer, response_error = await self._call_responder(
                decision.primary_agent,
                question,
                {"session_id": session_id, "user_id": user_id},
            )
            if normalized_answer is None:
                answer = {
                    "answer": None,
                    "facts": {},
                    "primary_agent": decision.primary_agent,
                    "abstain_reason": response_error or "response_invalid",
                    "handoff_needed": True,
                }
            else:
                answer = normalized_answer
                contributor_answers, contributor_errors = await self._ask_contributors(
                    decision.contributors,
                    question=question,
                    session_id=session_id,
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

        turn = Turn(
            turn_index=_next_turn_index(session),
            question=question,
            primary_agent=decision.primary_agent,
            answer=answer,
            decision=decision,
        )
        _append_turn(session, turn)
        await self._publish_turn(session_id=session_id, turn=turn)
        if answer.get("handoff_needed") and materialize_handoff:
            await self._publish_handoff(
                session_id=session_id,
                question=question,
                turn_index=turn.turn_index,
                reason=str(answer.get("abstain_reason") or "no_route"),
            )
        return turn

    async def _publish_turn(self, *, session_id: str, turn: Turn) -> None:
        if self.bus is None:
            return
        session_digest = hashlib.sha256(session_id.encode()).hexdigest()
        question_digest = hashlib.sha256(turn.question.encode()).hexdigest()
        answer_json = json.dumps(
            turn.answer,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
        trace_ref = str(
            turn.answer.get("trace_ref") or turn.answer.get("correlation_id") or session_id
        )
        turn_key = f"{session_digest}:{turn.turn_index}"
        turn_id = f"turn-{hashlib.sha256(turn_key.encode()).hexdigest()[:32]}"
        primary_agent = turn.primary_agent or "Bragi"
        contributors = turn.answer.get("contributors")
        safe_contributors = (
            [item for item in contributors[:_MAX_CONTRIBUTORS] if isinstance(item, str)]
            if isinstance(contributors, list)
            else []
        )
        await self.bus.publish(
            "Bragi",
            "object.turn",
            {
                "producer_principal": "Bragi",
                "id": turn_id,
                "turn_id": turn_id,
                "correlation_id": trace_ref,
                "idempotency_key": f"turn:{session_digest}:{turn.turn_index}",
                "session_id": session_id,
                "turn_index": turn.turn_index,
                "question_ref": (
                    f"bragi-session:sha256:{session_digest}:turn:{turn.turn_index}:question"
                ),
                "question_sha256": question_digest,
                "primary_agent": primary_agent,
                "contributors": safe_contributors,
                "answer_ref": (
                    f"bragi-session:sha256:{session_digest}:turn:{turn.turn_index}:answer"
                ),
                "answer_sha256": answer_digest,
                "score_breakdown": {
                    "scores": dict(turn.decision.scores),
                    "tie_break": turn.decision.tie_break,
                    "method": turn.decision.method,
                    "semantic_score": turn.decision.semantic_score,
                    "semantic_margin": turn.decision.semantic_margin,
                    "provider_status": turn.decision.provider_status,
                },
                "trace_ref": trace_ref,
            },
        )

    async def _publish_a2a_turn(
        self,
        *,
        requester: str,
        target_agent: str,
        question: str,
        response: dict[str, Any],
    ) -> None:
        if self.bus is None:
            return
        question_digest = hashlib.sha256(question.encode()).hexdigest()
        answer_json = json.dumps(
            response,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
        trace_ref = str(response.get("trace_ref") or "")
        identity = hashlib.sha256(
            f"{requester}\0{target_agent}\0{trace_ref}\0{question_digest}".encode()
        ).hexdigest()
        turn_id = f"turn-{identity[:32]}"
        session_digest = hashlib.sha256(f"{requester}:{target_agent}".encode()).hexdigest()
        session_id = f"a2a-{session_digest[:32]}"
        await self.bus.publish(
            "Bragi",
            "object.turn",
            {
                "producer_principal": "Bragi",
                "id": turn_id,
                "turn_id": turn_id,
                "correlation_id": trace_ref or turn_id,
                "idempotency_key": f"a2a-turn:{identity}",
                "session_id": session_id,
                "turn_index": 0,
                "question_ref": f"a2a:sha256:{question_digest}:question",
                "question_sha256": question_digest,
                "primary_agent": target_agent,
                "contributors": [],
                "answer_ref": f"a2a:sha256:{answer_digest}:answer",
                "answer_sha256": answer_digest,
                "score_breakdown": {
                    "requester": requester,
                    "routing": "direct_a2a",
                },
                "trace_ref": trace_ref or turn_id,
            },
        )

    async def _publish_handoff(
        self,
        *,
        session_id: str,
        question: str,
        turn_index: int,
        reason: str,
    ) -> None:
        if self.bus is None:
            return
        normalized = " ".join(question.split()).casefold()
        selector_digest = hashlib.sha256(normalized.encode()).hexdigest()
        escalation_id = hashlib.sha256(
            f"{session_id}\0{turn_index}\0{reason}\0{selector_digest}".encode()
        ).hexdigest()
        await self.bus.publish(
            "Bragi",
            "object.handoff-escalation",
            {
                "producer_principal": "Bragi",
                "id": f"handoff-{escalation_id[:32]}",
                "escalation_id": f"handoff-{escalation_id[:32]}",
                "correlation_id": session_id,
                "idempotency_key": f"handoff:{escalation_id}",
                "emitting_agent": "Bragi",
                "intent_category": reason,
                "normalized_selector": f"sha256:{selector_digest}",
                "failure_reason_code": reason,
                "emitted_at": datetime.now(UTC).isoformat(),
            },
        )

    async def _ask_contributors(
        self,
        contributors: tuple[str, ...],
        *,
        question: str,
        session_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return await ask_contributors(
            self._agent_responders,
            contributors,
            question=question,
            session_id=session_id,
            limit=_MAX_CONTRIBUTORS,
            timeout_seconds=_CONTRIBUTOR_TIMEOUT_SECONDS,
            logger=_LOG,
        )

    def prior_turns(self, session_id: str, *, limit: int = 5) -> tuple[Turn, ...]:
        session = self._sessions.get(session_id)
        if session is None:
            return ()
        return tuple(session.turns[-limit:])

    def sessions_for(self, user_id: str) -> tuple[ConversationSession, ...]:
        return tuple(s for s in self._sessions.values() if s.user_id == user_id)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        roster = {spec.name: list(spec.question_domains) for spec in PANTHEON_SPECS}
        facts = {
            **capability_facts(self.spec),
            "roster": roster,
        }
        answer = (
            "I am the narrator: I route your question to the agent that owns it. "
            f"{len(PANTHEON_SPECS)} agents are reachable - ask about topics like "
            "cost, capacity, anomalies, action status, audit history, or rules."
        )
        return IntrospectionResult(answer=answer, facts=facts)


def _validate_question(question: str) -> None:
    if len(question) > _MAX_QUESTION_CHARS:
        raise ValueError("question MUST be at most 2000 characters")


def _next_turn_index(session: ConversationSession) -> int:
    return session.turns[-1].turn_index + 1 if session.turns else 0


def _append_turn(session: ConversationSession, turn: Turn) -> None:
    session.turns.append(turn)
    if len(session.turns) > _MAX_SESSION_TURNS:
        del session.turns[:-_MAX_SESSION_TURNS]


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession", "translate_action_intent"]
