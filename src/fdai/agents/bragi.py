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

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bragi_contributors import (
    AnswerFn,
    ask_contributors,
)
from fdai.agents._framework.bragi_contributors import (
    introspect_agent as call_introspection_responder,
)
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import append_submitted, evict_oldest, record_progress
from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bragi_routing import route_question, translate_action_intent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    is_action_intent,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS

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
_MAX_PROGRESS_KEYS = 5_000
#: Cap on progress steps retained per correlation. A pipeline has a handful of
#: lifecycle states, but at-least-once redelivery (or a chatty retry) could
#: append without limit, so the per-correlation list is bounded too - not just
#: the key count.
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 3
_CONTRIBUTOR_TIMEOUT_SECONDS = 2.0


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

    def __init__(self) -> None:
        super().__init__(spec=_BRAGI)
        self._sessions: dict[str, ConversationSession] = {}
        self._agent_responders: dict[str, AnswerFn] = {}
        self._proposal_sink: ProposalSink | None = None
        # Per-correlation pipeline progress, appended as verdict / action-run
        # states arrive on the typed port, so an operator can be told where
        # their submitted action is (submitted -> verdicted -> hil_pending ->
        # executing -> succeeded / denied). Bounded both ways: the key count
        # by _evict_oldest (_MAX_PROGRESS_KEYS) and each list's length by
        # _MAX_PROGRESS_STEPS, with redelivered steps deduped.
        self._progress: dict[str, list[dict[str, Any]]] = {}

    # ---- registration --------------------------------------------------

    def register_responder(self, agent_name: str, fn: AnswerFn) -> None:
        self._agent_responders[agent_name] = fn

    def register_proposal_sink(self, fn: ProposalSink) -> None:
        """Wire the typed-pipeline entry (composition root binds Huginn.ingest).

        Without a sink, an action request falls back to the
        ``requires_typed_pipeline`` signal (no pipeline available) so behavior
        is unchanged where the pantheon is not wired.
        """
        self._proposal_sink = fn

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
        await self._proposal_sink(proposal)
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
        if requester not in PANTHEON_NAMES:
            # A2A is pantheon-internal: an unknown requester would poison the
            # audit trail (spoofed "who asked"). Reject at the boundary.
            raise ValueError(f"unknown requester agent: {requester!r}")
        ctx: dict[str, Any] = {**(context or {}), "requester": requester, "a2a": True}
        return await call_introspection_responder(
            self._agent_responders,
            agent_name,
            question,
            requester=requester,
            context=ctx,
        )

    # ---- routing -------------------------------------------------------

    def route(self, question: str) -> RoutingDecision:
        return route_question(question, max_contributors=_MAX_CONTRIBUTORS)

    # ---- session -------------------------------------------------------

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        initiator_role: str | None = None,
        allow_action_proposal: bool = True,
    ) -> Turn:
        """Route + call primary + record the turn.

        ``initiator_role`` (the console session's Entra role) is applied by the
        entry RBAC gate when the turn is an action command; ``None`` skips it.
        A read-only channel sets ``allow_action_proposal=False`` so an action
        utterance is redirected to the dedicated proposal route without
        publishing anything from the conversational port.
        """
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
                turn_index=len(session.turns),
                question=question,
                primary_agent=None,
                answer=answer,
                decision=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            )
            session.turns.append(turn)
            return turn
        decision = self.route(question)
        if decision.primary_agent is None:
            answer = {
                "answer": None,
                "primary_agent": None,
                "abstain_reason": "no_route",
                "handoff_needed": True,
            }
        else:
            responder = self._agent_responders.get(decision.primary_agent)
            if responder is None:
                answer = {
                    "answer": None,
                    "primary_agent": decision.primary_agent,
                    "abstain_reason": "responder_not_registered",
                }
            else:
                answer = await responder(
                    question,
                    {"session_id": session_id, "user_id": user_id},
                )
                answer.setdefault("primary_agent", decision.primary_agent)
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
                if isinstance(primary_text, str) and contributor_answers:
                    lines = [f"{decision.primary_agent}: {primary_text}"]
                    lines.extend(
                        f"{item['agent']}: {item['answer']}"
                        for item in contributor_answers
                        if isinstance(item.get("answer"), str)
                    )
                    answer["answer"] = "\n".join(lines)
                answer["score_breakdown"] = decision.scores
                answer["tie_break_reason"] = decision.tie_break

        turn = Turn(
            turn_index=len(session.turns),
            question=question,
            primary_agent=decision.primary_agent,
            answer=answer,
            decision=decision,
        )
        session.turns.append(turn)
        return turn

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


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession", "translate_action_intent"]
