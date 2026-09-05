"""Bragi translator over bounded structured semantic judgment.

Bragi maps an operator turn onto canonical Pantheon capabilities, gathers
read-only owned evidence, and renders the result. Candidate meaning never
grants execution authority; direct action requests re-enter the typed pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
)

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bragi_contributors import (
    AnswerFn,
    ask_contributors,
    evidence_conflicts,
    normalize_responder_answer,
)
from fdai.agents._framework.bragi_diagnostics import attach_pantheon_diagnostics
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import append_submitted, evict_oldest, record_progress
from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bragi_publication import (
    a2a_turn_event_payload,
    handoff_event_payload,
    turn_event_payload,
)
from fdai.agents._framework.bragi_routing import (
    route_semantic_judgment,
    semantic_capabilities,
)
from fdai.agents._framework.deliberation import (
    ConversationDeliberator,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.semantic_routing import SemanticAgentRouter
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.metering.budget import BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink

_LOG = logging.getLogger(__name__)

#: A proposal sink accepts one raw operator ActionProposal and hands it to the
#: typed pipeline (the composition root wires this to ``Huginn.ingest`` - the
#: sole writer of ``object.event``). Returns the normalized event payload, or
#: ``None`` when the collector deduplicated it. Bragi NEVER calls an executor
#: (agent-pantheon.md 7.7); it only submits through this sink.
ProposalSink = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
ToolAnswerFn = Callable[[str, str, str], Awaitable[dict[str, Any] | None]]

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
        semantic_judgment: SemanticJudgmentBoundary | None = None,
        action_type_names: Collection[str] = (),
        semantic_router: SemanticAgentRouter | None = None,
        t2_synthesizer: T2ConversationSynthesizer | None = None,
        escalation_budget: ModelBudget | None = None,
        escalation_ledger: BudgetLedger | None = None,
        pricing: PricingTable | None = None,
        metering: MeteringSink | None = None,
        t2_model_key: str = "",
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
        self._tool_answer: ToolAnswerFn | None = None
        self._semantic_judgment = semantic_judgment
        self._action_type_names = frozenset(action_type_names)
        self._semantic_router = semantic_router
        self._responder_timeout_seconds = responder_timeout_seconds
        self._proposal_timeout_seconds = proposal_timeout_seconds
        self._deliberator = ConversationDeliberator(
            specs=PANTHEON_SPECS,
            semantic_router=semantic_router,
            t2_synthesizer=t2_synthesizer,
            call_responder=self._call_responder,
            escalation_budget=escalation_budget,
            escalation_ledger=escalation_ledger,
            pricing=pricing,
            metering=metering,
            t2_model_key=t2_model_key,
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

    def register_tool_answer(self, fn: ToolAnswerFn) -> None:
        """Bind one mechanical owner-tool answer path at composition time."""

        if self._tool_answer is not None:
            raise ValueError("tool answer dispatcher already registered")
        self._tool_answer = fn

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
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        judgment: SemanticJudgmentProposal,
        initiator_role: str | None = None,
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
            judgment=judgment,
            action_type_names=self._action_type_names,
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
        if self._semantic_judgment is None:
            return {
                "requester": requester,
                "trace_ref": correlation_id,
                "authority": "presentation_only",
                "rounds": [],
                "status": "abstain",
                "reason": "semantic_unavailable",
            }
        judgment_result = await asyncio.to_thread(
            self._semantic_judgment.judge,
            utterance=question,
            context=(),
            capabilities=semantic_capabilities(self._action_type_names),
        )
        judgment = judgment_result.proposal if judgment_result.accepted else None
        if judgment is None:
            return {
                "requester": requester,
                "trace_ref": correlation_id,
                "authority": "presentation_only",
                "rounds": [],
                "status": "abstain",
                "reason": "semantic_unavailable",
            }
        if judgment.action_posture == "draft_only":
            return {
                "requester": requester,
                "trace_ref": correlation_id,
                "authority": "presentation_only",
                "rounds": [],
                "status": "abstain",
                "reason": "requires_typed_pipeline",
                "requires_typed_pipeline": True,
            }
        return await self._deliberator.deliberate(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
            routing_decision=self.route(judgment),
        )

    # ---- routing -------------------------------------------------------

    def route(self, judgment: SemanticJudgmentProposal) -> RoutingDecision:
        return route_semantic_judgment(
            judgment,
            max_contributors=_MAX_CONTRIBUTORS,
        )

    def should_delegate(self, question: str, view_context: dict[str, Any]) -> bool:
        """Return whether a question needs agent-owned state beyond the screen."""
        route_id = str(view_context.get("routeId") or "").strip()
        has_screen_snapshot = "facts" in view_context or "records" in view_context
        if not route_id or not has_screen_snapshot:
            return True
        result = self._judge(
            question,
            context=(f"screen_route={route_id}", "screen_snapshot_available=true"),
        )
        return not (
            result is not None
            and result.primary_intent == "current_screen_data"
            and "current_screen" in result.requested_facets
        )

    def _judge(
        self,
        question: str,
        *,
        context: tuple[str, ...],
    ) -> SemanticJudgmentProposal | None:
        if self._semantic_judgment is None:
            return None
        result = self._semantic_judgment.judge(
            utterance=question,
            context=context,
            capabilities=semantic_capabilities(self._action_type_names),
        )
        return result.proposal if result.accepted else None

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
        judgment_result = (
            await asyncio.to_thread(
                self._semantic_judgment.judge,
                utterance=question,
                context=tuple(turn.question for turn in session.turns[-8:]),
                capabilities=semantic_capabilities(self._action_type_names),
            )
            if self._semantic_judgment is not None
            else None
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
                turn_index=_next_turn_index(session),
                question=question,
                primary_agent=None,
                answer=answer,
                decision=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            )
            _append_turn(session, turn)
            await self._publish_turn(session_id=session_id, turn=turn)
            return turn
        decision = (
            self.route(judgment)
            if judgment is not None
            else RoutingDecision(
                primary_agent=None,
                scores={},
                tie_break=None,
                method="semantic_unavailable",
                provider_status=(
                    judgment_result.receipt.disposition.value
                    if judgment_result is not None
                    else "unbound"
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
                        "session_id": session_id,
                        "user_id": user_id,
                        "semantic_action_posture": judgment.action_posture,
                        "semantic_requested_facets": judgment.requested_facets,
                        "semantic_primary_intent": judgment.primary_intent,
                        "semantic_targets": tuple(
                            target.model_dump(mode="json") for target in judgment.targets
                        ),
                    },
                )
            else:
                normalized_answer, response_error = normalize_responder_answer(
                    decision.primary_agent,
                    tool_answer,
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
            else:
                answer = normalized_answer
                if not isinstance(answer.get("answer"), str):
                    answer["handoff_needed"] = True
                    contributor_answers: list[dict[str, Any]] = []
                    contributor_errors: list[str] = []
                else:
                    contributor_answers, contributor_errors = await self._ask_contributors(
                        decision.contributors,
                        question=question,
                        session_id=session_id,
                        primary_agent=decision.primary_agent,
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
                "execution_authority": False,
            }

        attach_pantheon_diagnostics(
            answer=answer,
            decision=decision,
            question=question,
            session_id=session_id,
        )

        turn_index = _next_turn_index(session)
        if answer.get("handoff_needed") and materialize_handoff:
            answer["handoff_status"] = await self._publish_handoff(
                session_id=session_id,
                question=question,
                turn_index=turn_index,
                reason=str(answer.get("abstain_reason") or "no_route"),
            )
        turn = Turn(
            turn_index=turn_index,
            question=question,
            primary_agent=decision.primary_agent,
            answer=answer,
            decision=decision,
        )
        _append_turn(session, turn)
        await self._publish_turn(session_id=session_id, turn=turn)
        return turn

    async def _publish_turn(self, *, session_id: str, turn: Turn) -> None:
        if self.bus is None:
            return
        await self.bus.publish(
            "Bragi",
            "object.turn",
            turn_event_payload(
                session_id=session_id,
                turn=turn,
                contributor_limit=_MAX_CONTRIBUTORS,
            ),
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
        await self.bus.publish(
            "Bragi",
            "object.turn",
            a2a_turn_event_payload(
                requester=requester,
                target_agent=target_agent,
                question=question,
                response=response,
            ),
        )

    async def _publish_handoff(
        self,
        *,
        session_id: str,
        question: str,
        turn_index: int,
        reason: str,
    ) -> str:
        if self.bus is None:
            self.record_behavior("handoff:transport_unavailable")
            return "transport_unavailable"
        try:
            await self.bus.publish(
                "Bragi",
                "object.handoff-escalation",
                handoff_event_payload(
                    session_id=session_id,
                    question=question,
                    turn_index=turn_index,
                    reason=reason,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - bounded operator degradation
            self.record_behavior("handoff:publish_failed")
            _LOG.warning(
                "handoff_publish_failed",
                extra={"error_type": type(exc).__name__},
            )
            return "publish_failed"
        self.record_behavior("handoff:published")
        return "published"

    async def _ask_contributors(
        self,
        contributors: tuple[str, ...],
        *,
        question: str,
        session_id: str,
        primary_agent: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return await ask_contributors(
            self._agent_responders,
            contributors,
            question=question,
            session_id=session_id,
            limit=_MAX_CONTRIBUTORS,
            timeout_seconds=_CONTRIBUTOR_TIMEOUT_SECONDS,
            logger=_LOG,
            primary_agent=primary_agent,
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


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession"]
