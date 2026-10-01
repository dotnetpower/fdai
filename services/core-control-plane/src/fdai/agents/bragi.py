"""Bragi translator over bounded structured semantic judgment.

Bragi maps an operator turn onto canonical Pantheon capabilities, gathers
read-only owned evidence, and renders the result. Candidate meaning never
grants execution authority; direct action requests re-enter the typed pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable, Collection, Mapping
from datetime import UTC, datetime, timedelta
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
from fdai.agents._framework.bragi_intent_training import (
    IntentTrainingEvaluator,
    IntentTrainingEvidence,
    IntentTrainingRun,
    ReviewedIntentTrainingPromotion,
    build_unbound_training_payload,
    evaluate_training_contract,
)
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import append_submitted, evict_oldest, record_progress
from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bragi_publication import (
    BragiPublicationMixin,
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
    agent_state_evidence_ref,
    capability_facts,
    durable_evidence_refs,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.role_answers import bragi_role_answer
from fdai.agents._framework.semantic_routing import SemanticAgentRouter
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.metering.budget import BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.user_context import UserPreferenceRecord

_LOG = logging.getLogger(__name__)
_BRAGI_STATE_PREFIX = "pantheon/bragi"
_INTENT_TRAINING_EVIDENCE_PREFIX = f"{_BRAGI_STATE_PREFIX}/intent-training/"
_INTENT_TRAINING_EVIDENCE_RETENTION = 1_024
_USER_PREFERENCE_INDEX_PREFIX = f"{_BRAGI_STATE_PREFIX}/user-preference-index/"
_USER_PREFERENCE_INDEX_SCAN_LIMIT = 1_000
_TURN_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_TURN_OUTBOX_TOMBSTONE_RETENTION = 1_024

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
_DURABLE_PROGRESS_RETENTION = _MAX_PROGRESS_KEYS
#: Cap on progress steps retained per correlation. A pipeline has a handful of
#: lifecycle states, but at-least-once redelivery (or a chatty retry) could
#: append without limit, so the per-correlation list is bounded too - not just
#: the key count.
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 2
_CONTRIBUTOR_TIMEOUT_SECONDS = 1.2
_RESPONDER_TIMEOUT_SECONDS = 2.0
_PROPOSAL_TIMEOUT_SECONDS = 5.0
_SEMANTIC_JUDGMENT_TIMEOUT_SECONDS = 2.0
_SESSION_INACTIVITY_LIMIT = timedelta(minutes=30)


#: Entry RBAC gate for execute-class conversational requests. A console
#: session's Entra role is mapped to the canonical capability matrix
#: (:mod:`fdai.core.rbac.roles`) and MUST carry ``AUTHOR_DRAFT_PR`` to submit an
#: action - the SAME capability the HTTP console-action route requires, so the
#: two entry surfaces never drift. In particular ``BreakGlass`` is hard-isolated
#: (NOT a superset of Owner) and does NOT carry ``AUTHOR_DRAFT_PR``, so it cannot
#: submit a normal action from either surface. Refused before the proposal
#: enters the pipeline (defense-in-depth with Forseti's principal-level RBAC
#: deny).
class Bragi(BragiPublicationMixin, Agent):
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
        semantic_judgment_timeout_seconds: float = _SEMANTIC_JUDGMENT_TIMEOUT_SECONDS,
        state_store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if responder_timeout_seconds <= 0:
            raise ValueError("responder timeout MUST be positive")
        if proposal_timeout_seconds <= 0:
            raise ValueError("proposal timeout MUST be positive")
        if (
            not math.isfinite(semantic_judgment_timeout_seconds)
            or semantic_judgment_timeout_seconds <= 0
        ):
            raise ValueError("semantic judgment timeout MUST be positive")
        super().__init__(spec=_BRAGI)
        self._sessions: dict[str, ConversationSession] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._agent_responders: dict[str, AnswerFn] = {}
        self._proposal_sink: ProposalSink | None = None
        self._tool_answer: ToolAnswerFn | None = None
        self._semantic_judgment = semantic_judgment
        self._semantic_judgment_timeout_seconds = semantic_judgment_timeout_seconds
        self._action_type_names = frozenset(action_type_names)
        self._semantic_router = semantic_router
        self._intent_training_evaluator: IntentTrainingEvaluator | None = None
        self._last_intent_training: dict[str, Any] | None = None
        self._last_intent_training_retention: dict[str, Any] = {
            "evidence_state": "not_configured",
            "retained": False,
            "reason": "state_store_unbound",
        }
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
        self._state_store = state_store
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._a2a_turn_indexes: dict[tuple[str, str], int] = {}
        self._turn_outbox_pending = 0
        self._last_preference_index_refresh: dict[str, Any] | None = None

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

    def register_intent_training_evaluator(self, evaluator: IntentTrainingEvaluator) -> None:
        """Bind Bragi's off-path deterministic intent-training evaluator."""

        if self._intent_training_evaluator is not None:
            raise ValueError("intent training evaluator already registered")
        self._intent_training_evaluator = evaluator

    async def run_intent_training(
        self,
        corpus: Collection[IntentTrainingEvidence],
        *,
        reviewed_promotion: ReviewedIntentTrainingPromotion | None = None,
    ) -> IntentTrainingRun:
        """Evaluate one inert Bragi intent-classifier candidate off the hot path.

        The run publishes Bragi-owned model-quality evidence and never replaces
        the runtime semantic judgment, routing table, owner selection, or typed
        pipeline authority.
        """

        if self._intent_training_evaluator is None:
            payload = build_unbound_training_payload(reason="training_evaluator_unbound")
            retention = await self._retain_intent_training_evidence(payload)
            published = await self._publish_intent_training_evidence(payload)
            self.record_behavior("intent_training:no_op_unbound")
            self._last_intent_training = {
                "status": "no_op",
                "reason": "training_evaluator_unbound",
                "published": published,
                "audit_evidence_retained": retention["retained"],
            }
            return IntentTrainingRun(
                run_id=str(payload["id"]),
                payload=payload,
                candidate_revision=None,
                gate_passed=False,
                published=published,
            )
        payload, candidate, gate_passed = evaluate_training_contract(
            tuple(corpus),
            evaluator=self._intent_training_evaluator,
            reviewed_promotion=reviewed_promotion,
        )
        retention = await self._retain_intent_training_evidence(payload)
        published = await self._publish_intent_training_evidence(payload)
        gate_status = str(payload["stages"]["regression_gate"]["status"])
        promotion_status = str(payload["stages"]["promotion_decision"]["status"])
        self.record_behavior(f"intent_training:gate_{gate_status}")
        self.record_behavior(f"intent_training:promotion_{promotion_status}")
        self._last_intent_training = {
            "status": promotion_status,
            "gate_status": gate_status,
            "published": published,
            "candidate_digest": candidate.get("candidate_digest")
            if candidate is not None
            else None,
            "audit_evidence_retained": retention["retained"],
            "runtime_routing_authority_changed": False,
        }
        return IntentTrainingRun(
            run_id=str(payload["id"]),
            payload=payload,
            candidate_revision=candidate,
            gate_passed=gate_passed,
            published=published,
        )

    async def _publish_intent_training_evidence(self, payload: dict[str, Any]) -> bool:
        bus = self.bus
        if bus is None:
            self.record_behavior("intent_training:publication_unavailable")
            return False
        await bus.publish("Bragi", "object.post-turn-review", payload)
        return True

    async def _retain_intent_training_evidence(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._state_store is None:
            retention = {
                "evidence_state": "not_configured",
                "retained": False,
                "reason": "state_store_unbound",
            }
            self._last_intent_training_retention = retention
            self.record_behavior("intent_training:evidence_not_retained")
            return retention
        contract_version = str(payload.get("contract_version") or "")
        corpus_digest = str(payload.get("corpus_digest") or "")
        candidate_digest = str(payload.get("candidate_digest") or "")
        stages = payload.get("stages")
        if not contract_version or not corpus_digest or not candidate_digest:
            raise RuntimeError("intent training evidence requires contract and lineage digests")
        if not isinstance(stages, Mapping):
            raise RuntimeError("intent training evidence requires stage mapping")
        created = 0
        for stage_name, raw_stage in stages.items():
            if not isinstance(raw_stage, Mapping):
                raise RuntimeError("intent training stage MUST be a mapping")
            stage = str(stage_name)
            key = _intent_training_stage_key(
                contract_version=contract_version,
                corpus_digest=corpus_digest,
                candidate_digest=candidate_digest,
                stage=stage,
            )
            value = {
                "kind": "bragi_intent_training_stage",
                "revision": 1,
                "contract_version": contract_version,
                "corpus_digest": corpus_digest,
                "candidate_digest": candidate_digest,
                "stage": stage,
                "stage_status": str(raw_stage.get("status") or ""),
                "run_id": str(payload.get("id") or ""),
                "stage_payload": dict(raw_stage),
                "routes_runtime_traffic": False,
                "grants_action_authority": False,
            }
            audit = {
                "kind": "bragi_intent_training_stage_recorded",
                "principal": "Bragi",
                "contract_version": contract_version,
                "corpus_digest": corpus_digest,
                "candidate_digest": candidate_digest,
                "stage": stage,
                "stage_status": str(raw_stage.get("status") or ""),
                "routes_runtime_traffic": False,
                "grants_action_authority": False,
            }
            if await self._state_store.write_state_with_audit_if_absent(key, value, audit):
                created += 1
        await self._state_store.delete_states_beyond(
            _INTENT_TRAINING_EVIDENCE_PREFIX,
            retain_newest=_INTENT_TRAINING_EVIDENCE_RETENTION,
        )
        retention = {
            "evidence_state": "retained",
            "retained": True,
            "created_records": created,
            "stage_records": len(stages),
            "retention_limit": _INTENT_TRAINING_EVIDENCE_RETENTION,
        }
        self._last_intent_training_retention = retention
        self.record_behavior("intent_training:evidence_retained", created or 1)
        return retention

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
            self.record_behavior("responder:timeout")
            return None, "timeout"
        except Exception as exc:  # noqa: BLE001 - isolate one primary responder
            _LOG.warning(
                "bragi_responder_failed",
                extra={"agent": agent_name, "error_type": type(exc).__name__},
            )
            self.record_behavior("responder:error")
            return None, "responder_error"
        return normalize_responder_answer(agent_name, raw_response)

    async def _judge_async(
        self,
        question: str,
        *,
        context: tuple[str, ...],
    ) -> tuple[Any | None, str]:
        if self._semantic_judgment is None:
            return None, "unbound"
        try:
            return (
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._semantic_judgment.judge,
                        utterance=question,
                        context=context,
                        capabilities=semantic_capabilities(self._action_type_names),
                    ),
                    timeout=self._semantic_judgment_timeout_seconds,
                ),
                "ok",
            )
        except TimeoutError:
            self.record_behavior("semantic_judgment:timeout")
            _LOG.warning("bragi_semantic_judgment_timeout")
            return None, "timeout"

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

        ``initiator_role`` is mandatory for action re-entry. A missing or
        insufficient role refuses before proposal construction, so read-only
        channels cannot accidentally submit a typed action.
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
            self.record_behavior(f"proposal:{status.get('abstain_reason', 'not_submitted')}")
            return status
        try:
            sink_result = await asyncio.wait_for(
                self._proposal_sink(proposal),
                timeout=self._proposal_timeout_seconds,
            )
        except TimeoutError:
            _LOG.warning("bragi_proposal_timeout", extra={"action_type": status["action_type"]})
            self.record_behavior("proposal:timeout")
            return {**status, "submitted": False, "abstain_reason": "proposal_timeout"}
        except Exception as exc:  # noqa: BLE001 - isolate typed-pipeline handoff
            _LOG.warning(
                "bragi_proposal_failed",
                extra={
                    "action_type": status["action_type"],
                    "error_type": type(exc).__name__,
                },
            )
            await self._publish_denied_proposal(
                status=status,
                user_id=user_id,
                reason="proposal_sink_error",
                error_type=type(exc).__name__,
            )
            self.record_behavior("proposal:sink_error")
            return {**status, "submitted": False, "abstain_reason": "proposal_sink_error"}
        if sink_result is None:
            self.record_behavior("proposal:deduplicated")
            return {**status, "submitted": False, "deduplicated": True}
        correlation_id = str(status["correlation_id"])
        action_type = str(status["action_type"])
        append_submitted(
            self._progress,
            correlation_id,
            action_type,
            max_keys=_MAX_PROGRESS_KEYS,
        )
        self.record_behavior("proposal:submitted")
        return status

    # ---- typed port (progress rendering) -------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Record pipeline progress for a submitted proposal.

        Bragi subscribes to ``object.verdict`` and ``object.action-run`` only
        to render progress back to the operator (agent-pantheon.md 7.7 - Bragi
        renders, never executes). It appends the state; it publishes nothing.
        """
        outcome = record_progress(
            self._progress,
            topic,
            payload,
            max_keys=_MAX_PROGRESS_KEYS,
            max_steps=_MAX_PROGRESS_STEPS,
        )
        if outcome == "missing_correlation":
            self.record_behavior("progress:missing_correlation")
        elif outcome == "ignored_topic":
            self.record_behavior("progress:ignored_topic")
        elif outcome == "duplicate":
            self.record_behavior("progress:duplicate")
        elif outcome == "recorded":
            self.record_behavior("progress:recorded")
            await self._checkpoint_progress(topic, payload)
        return None

    def progress_for(self, correlation_id: str) -> list[dict[str, Any]]:
        """The recorded pipeline progress for one submitted proposal."""
        return list(self._progress.get(correlation_id, []))

    async def _checkpoint_progress(self, topic: str, payload: Mapping[str, Any]) -> None:
        if self._state_store is None:
            return
        correlation_id = str(payload.get("correlation_id") or "")
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not correlation_id or not idempotency_key:
            return
        step = self._progress.get(correlation_id, [])[-1]
        key_material = f"{topic}\0{correlation_id}\0{idempotency_key}\0{step.get('state')}"
        await self._state_store.write_state_if_absent(
            f"{_BRAGI_STATE_PREFIX}/progress/"
            f"{hashlib.sha256(key_material.encode('utf-8')).hexdigest()}",
            {
                "schema_version": "1.0.0",
                "correlation_id": correlation_id,
                "step": step,
            },
        )
        await self._state_store.delete_states_beyond(
            f"{_BRAGI_STATE_PREFIX}/progress/",
            retain_newest=_DURABLE_PROGRESS_RETENTION,
        )

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
        caller_context = context or {}
        if caller_context.get("nested_round") is True:
            self.record_behavior("a2a:nested_refused")
            return {
                "primary_agent": agent_name,
                "answer": None,
                "facts": {},
                "abstain_reason": "nested_round_refused",
                "requester": requester,
                "trace_ref": str(caller_context.get("correlation_id") or ""),
            }
        ctx: dict[str, Any] = {"requester": requester, "a2a": True}
        correlation_id = caller_context.get("correlation_id")
        if isinstance(correlation_id, str) and 0 < len(correlation_id) <= 256:
            ctx["correlation_id"] = correlation_id
        locale = caller_context.get("locale")
        if _locale_is_supported(locale):
            ctx["locale"] = locale
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
            turn_index=self._next_a2a_turn_index(requester, agent_name),
        )
        return response

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
        locale: str = "en",
        reuse_semantic_route: bool = True,
        fixed_assurance_facts: Mapping[str, Mapping[str, object]] | None = None,
        fixed_assurance_scenario_id: str | None = None,
    ) -> dict[str, Any]:
        """Delegate one bounded read-only discussion to the framework orchestrator."""
        _validate_question(question)
        if requester not in PANTHEON_NAMES:
            raise ValueError(f"unknown requester agent: {requester!r}")
        if len(correlation_id) > 256:
            raise ValueError("correlation_id MUST be at most 256 characters")
        if self._semantic_judgment is None:
            return {
                "requester": requester,
                "trace_ref": correlation_id,
                "authority": "presentation_only",
                "rounds": [],
                "status": "abstain",
                "reason": "semantic_unavailable",
            }
        judgment_result, judgment_status = await self._judge_async(question, context=())
        judgment = (
            judgment_result.proposal
            if judgment_result is not None and judgment_result.accepted
            else None
        )
        if judgment is None:
            return {
                "requester": requester,
                "trace_ref": correlation_id,
                "authority": "presentation_only",
                "rounds": [],
                "status": "abstain",
                "reason": "semantic_timeout"
                if judgment_status == "timeout"
                else "semantic_unavailable",
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
            locale=locale,
            routing_decision=self.route(judgment),
            fixed_assurance_facts=fixed_assurance_facts,
            fixed_assurance_scenario_id=fixed_assurance_scenario_id,
        )

    # ---- routing -------------------------------------------------------

    def route(
        self, judgment: SemanticJudgmentProposal, *, question: str | None = None
    ) -> RoutingDecision:
        return route_semantic_judgment(
            judgment, max_contributors=_MAX_CONTRIBUTORS, question=question
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

    async def _publish_turn(self, payload: dict[str, Any]) -> None:
        if self.bus is None:
            self.record_behavior("turn:publication_pending")
            return
        if not await self._claim_turn_publication(payload):
            return
        publish_task = asyncio.create_task(self.bus.publish("Bragi", "object.turn", payload))
        try:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_turn_published(payload))
        except asyncio.CancelledError:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_turn_published(payload))
            raise

    async def _reserve_turn_index(self, session_id: str, session: ConversationSession) -> int:
        if self._state_store is None:
            turn_index = session.next_turn_index
            session.next_turn_index += 1
            return turn_index
        key = _session_sequence_key(session_id)
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None:
                turn_index = session.next_turn_index
                record = {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "session_id": session_id,
                    "next_turn_index": turn_index + 1,
                }
                if await self._state_store.write_state_if_absent(key, record):
                    session.next_turn_index = max(session.next_turn_index, turn_index + 1)
                    return turn_index
                continue
            next_index = stored.get("next_turn_index")
            revision = stored.get("revision")
            if (
                stored.get("schema_version") != "1.0.0"
                or not isinstance(next_index, int)
                or isinstance(next_index, bool)
                or next_index < 0
                or not isinstance(revision, int)
                or isinstance(revision, bool)
            ):
                raise RuntimeError("durable Bragi turn sequence is malformed")
            advanced = await self._state_store.compare_and_set_state(
                key,
                {**dict(stored), "revision": revision + 1, "next_turn_index": next_index + 1},
                expected_revision=revision,
            )
            if advanced:
                session.next_turn_index = max(session.next_turn_index, next_index + 1)
                return next_index
        raise RuntimeError("Bragi turn sequence CAS retry limit exceeded")

    async def _checkpoint_turn_payload(
        self, *, session: ConversationSession, turn: Turn
    ) -> dict[str, Any]:
        payload = turn_event_payload(
            session_id=session.session_id,
            user_id=session.user_id,
            session_generation=session.generation,
            turn=turn,
            contributor_limit=_MAX_CONTRIBUTORS,
        )
        if self._state_store is None:
            return payload
        key = _turn_outbox_key(str(payload["session_ref"]), turn.turn_index)
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "session_ref": payload["session_ref"],
            "turn_index": turn.turn_index,
            "payload": payload,
        }
        created = await self._state_store.write_state_if_absent(key, record)
        if created:
            self._turn_outbox_pending += 1
            return payload
        stored = await self._state_store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Bragi turn outbox row disappeared")
        stored_payload = stored.get("payload")
        if stored.get("status") == "published":
            if isinstance(stored_payload, Mapping):
                return dict(stored_payload)
            stored_digest = str(stored.get("payload_digest") or "")
            payload_digest = _payload_digest(payload)
            if stored_digest and stored_digest != payload_digest:
                raise RuntimeError("Bragi turn outbox idempotency collision")
            return payload
        revision = int(stored.get("revision", 1))
        advanced = await self._state_store.compare_and_set_state(
            key,
            {**record, "revision": revision + 1},
            expected_revision=revision,
        )
        if not advanced:
            raise RuntimeError("Bragi turn outbox update conflicted")
        self._turn_outbox_pending += 1
        return payload

    async def _claim_turn_publication(self, payload: Mapping[str, Any]) -> bool:
        if self._state_store is None:
            return True
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None:
                raise RuntimeError("Bragi turn outbox row disappeared before publication")
            status = stored.get("status")
            if status == "published":
                return False
            if status == "publishing":
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                {**dict(stored), "status": "publishing", "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return True
        raise RuntimeError("Bragi turn publication claim CAS retry limit exceeded")

    async def _mark_turn_published(self, payload: Mapping[str, Any]) -> None:
        if self._state_store is None:
            return
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                _published_turn_outbox_tombstone(stored, revision=revision + 1),
                expected_revision=revision,
            )
            if advanced:
                await self._compact_turn_outbox_tombstones()
                self._turn_outbox_pending = max(0, self._turn_outbox_pending - 1)
                return
        raise RuntimeError("Bragi turn publication CAS retry limit exceeded")

    async def _compact_turn_outbox_tombstones(self) -> None:
        if self._state_store is None:
            return
        await self._state_store.delete_states_beyond(
            f"{_BRAGI_STATE_PREFIX}/turn-outbox/",
            retain_newest=_TURN_OUTBOX_PENDING_SCAN_LIMIT + _TURN_OUTBOX_TOMBSTONE_RETENTION,
        )

    async def recover_state(self) -> tuple[int, int]:
        """Restore durable progress and unpublished turn outbox rows."""

        if self._state_store is None:
            return 0, 0
        progress_rows = await self._state_store.read_states(
            f"{_BRAGI_STATE_PREFIX}/progress/",
            limit=_MAX_PROGRESS_KEYS * _MAX_PROGRESS_STEPS,
        )
        progress = 0
        for row in reversed(progress_rows):
            correlation_id = str(row.get("correlation_id") or "")
            step = row.get("step")
            if correlation_id and isinstance(step, Mapping):
                self._progress.setdefault(correlation_id, []).append(dict(step))
                self._progress[correlation_id] = self._progress[correlation_id][
                    -_MAX_PROGRESS_STEPS:
                ]
                progress += 1
        published = 0
        if self.bus is not None:
            rows, _total = await self._state_store.read_state_page(
                f"{_BRAGI_STATE_PREFIX}/turn-outbox/",
                limit=_TURN_OUTBOX_PENDING_SCAN_LIMIT,
                field="status",
                value="pending",
            )
            self._turn_outbox_pending = _total
            for row in reversed(rows):
                payload = row.get("payload")
                if not isinstance(payload, Mapping):
                    raise RuntimeError("Bragi turn outbox row is malformed")
                if await self._claim_turn_publication(payload):
                    publish_task = asyncio.create_task(
                        self.bus.publish("Bragi", "object.turn", dict(payload))
                    )
                    try:
                        await asyncio.shield(publish_task)
                        await asyncio.shield(self._mark_turn_published(payload))
                    except asyncio.CancelledError:
                        await asyncio.shield(publish_task)
                        await asyncio.shield(self._mark_turn_published(payload))
                        raise
                    published += 1
        recovered_publications = await self.recover_bragi_publications()
        self._turn_outbox_pending = max(0, self._turn_outbox_pending - published)
        return progress, published + recovered_publications

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        refreshed = await self.refresh_user_preference_index()
        if refreshed:
            self.record_behavior("maintenance_tick:user_preference_index_refreshed", refreshed)

    async def refresh_user_preference_index(self) -> int:
        """Republish bounded durable UserPreference rows without changing routing authority."""

        if self._state_store is None:
            self._last_preference_index_refresh = {
                "refreshed_at": self._clock().isoformat(),
                "rows_scanned": 0,
                "preferences_published": 0,
                "evidence_state": "not_configured",
                "execution_authority": False,
            }
            return 0
        rows = await self._state_store.read_states(
            _USER_PREFERENCE_INDEX_PREFIX,
            limit=_USER_PREFERENCE_INDEX_SCAN_LIMIT,
        )
        published = 0
        invalid = 0
        for row in rows:
            try:
                preference = _preference_from_index_row(row)
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if await self.publish_user_preference(preference):
                published += 1
        self._last_preference_index_refresh = {
            "refreshed_at": self._clock().isoformat(),
            "rows_scanned": len(rows),
            "preferences_published": published,
            "invalid_rows": invalid,
            "evidence_state": "measured",
            "execution_authority": False,
        }
        if invalid:
            self.record_behavior("user_preference_index:invalid_row", invalid)
        return published

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
    ) -> str:
        payload = handoff_event_payload(
            session_id=session_id,
            question=question,
            turn_index=turn_index,
            intent_category=intent_category,
            resource_type=resource_type,
            primary_agent=primary_agent,
            failure_reason_code=failure_reason_code,
            emitted_at=self._clock(),
        )
        try:
            published = await self.publish_handoff_event(payload)
        except Exception as exc:  # noqa: BLE001 - bounded operator degradation
            self.record_behavior("publication:unavailable")
            _LOG.warning(
                "handoff_publish_failed",
                extra={"error_type": type(exc).__name__},
            )
            return "publish_failed"
        if not published:
            self.record_behavior("publication:unavailable")
            return "transport_unavailable"
        self.record_behavior("handoff:materialized")
        return "requested"

    async def _publish_denied_proposal(
        self,
        *,
        status: Mapping[str, Any],
        user_id: str,
        reason: str,
        error_type: str,
    ) -> None:
        principal_digest = hashlib.sha256(user_id.encode()).hexdigest()
        correlation_id = str(status.get("correlation_id") or "")
        action_type = str(status.get("action_type") or "")
        if not correlation_id:
            correlation_id = (
                "proposal-denied-"
                + hashlib.sha256(
                    f"{principal_digest}\0{action_type}\0{reason}".encode()
                ).hexdigest()[:32]
            )
        payload = {
            "producer_principal": "Bragi",
            "kind": "operator_proposal_denied",
            "id": f"proposal-denied-{hashlib.sha256(correlation_id.encode()).hexdigest()[:32]}",
            "correlation_id": correlation_id,
            "idempotency_key": f"operator-proposal-denied:{correlation_id}:{reason}",
            "emitting_agent": "Bragi",
            "primary_agent": "Bragi",
            "intent_category": "operator_action_reentry",
            "resource_type": str(status.get("resource_type") or "unknown"),
            "failure_reason_code": reason,
            "action_type": action_type,
            "principal_scope": f"sha256:{principal_digest}",
            "error_type": error_type,
            "execution_authority": False,
        }
        try:
            if await self.publish_handoff_event(payload):
                self.record_behavior("proposal:denial_audited")
            else:
                self.record_behavior("proposal:denial_audit_unavailable")
        except Exception as exc:  # noqa: BLE001 - original proposal failure remains isolated
            _LOG.warning(
                "bragi_proposal_denial_audit_failed",
                extra={"error_type": type(exc).__name__},
            )
            self.record_behavior("proposal:denial_audit_failed")

    def prior_turns(self, session_id: str, *, limit: int = 5) -> tuple[Turn, ...]:
        session = self._sessions.get(session_id)
        if session is None:
            return ()
        return tuple(session.turns[-limit:])

    def sessions_for(self, user_id: str) -> tuple[ConversationSession, ...]:
        return tuple(s for s in self._sessions.values() if s.user_id == user_id)

    def health(self) -> dict[str, Any]:
        behavior = self.behavior_snapshot()
        materialized = int(behavior.get("handoff:materialized", 0) or 0)
        failed = int(behavior.get("publication:unavailable", 0) or 0)
        total = materialized + failed
        handoff_kpi = (
            {
                "value": materialized / total,
                "evidence_state": "measured",
                "numerator": materialized,
                "denominator": total,
                "unit": "ratio",
            }
            if total
            else {
                "value": None,
                "evidence_state": "insufficient_sample",
                "numerator": 0,
                "denominator": 0,
                "unit": "ratio",
            }
        )
        return {
            "agent": self.spec.name,
            "status": "ok",
            "session_durability": "durable" if self._state_store is not None else "process_local",
            "active_sessions": len(self._sessions),
            "pending_turn_outbox": self._turn_outbox_pending,
            "last_preference_index_refresh": self._last_preference_index_refresh,
            "intent_training": {
                "mode": "off_path_shadow",
                "status": "enabled"
                if self._intent_training_evaluator is not None
                else "unavailable",
                "warning": None
                if self._intent_training_evaluator is not None
                else "intent_training_evaluator_unbound",
                "evidence_retention": self._last_intent_training_retention,
                "last_run": self._last_intent_training,
                "runtime_routing_authority": False,
            },
            "handoff_publication": {
                "materialized": materialized,
                "failed": failed,
                "denominator": total,
            },
            "fallback": {
                "console_read_only_available": "unknown",
                "direct_audit_query_available": "unknown",
            },
            "kpis": {"handoff_rate": handoff_kpi},
            "behavior": behavior,
        }

    def _next_a2a_turn_index(self, requester: str, target_agent: str) -> int:
        key = (requester, target_agent)
        turn_index = self._a2a_turn_indexes.get(key, 0)
        self._a2a_turn_indexes[key] = turn_index + 1
        return turn_index

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        roster = {spec.name: list(spec.question_domains) for spec in PANTHEON_SPECS}
        facts = {
            **capability_facts(self.spec),
            "roster": roster,
        }
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        answer = bragi_role_answer(str(context.get("locale")), len(PANTHEON_SPECS), evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)


def _validate_question(question: str) -> None:
    if len(question) > _MAX_QUESTION_CHARS:
        raise ValueError("question MUST be at most 2000 characters")


def _locale_is_supported(locale: object) -> bool:
    return locale == "en" or locale == "ko"


def _validate_tool_answer_envelope(agent_name: str, answer: Mapping[str, Any]) -> str | None:
    facts = answer.get("facts")
    if not isinstance(facts, Mapping):
        return "tool_answer_invalid"
    if not durable_evidence_refs(facts.get("evidence_refs"), agent_name=agent_name):
        return "tool_evidence_incomplete"
    results = answer.get("conversation_tool_results")
    if not isinstance(results, list) or not results:
        return "tool_evidence_incomplete"
    for result in results:
        if not isinstance(result, Mapping):
            return "tool_evidence_incomplete"
        if result.get("status") != "ok":
            return str(result.get("reason") or "tool_evidence_incomplete")
        count = result.get("evidence_ref_count")
        if not isinstance(count, int) or count <= 0:
            return "tool_evidence_incomplete"
    return None


def _next_turn_index(session: ConversationSession) -> int:
    return session.turns[-1].turn_index + 1 if session.turns else 0


def _append_turn(session: ConversationSession, turn: Turn) -> None:
    session.turns.append(turn)
    session.next_turn_index = max(session.next_turn_index, turn.turn_index + 1)
    if len(session.turns) > _MAX_SESSION_TURNS:
        del session.turns[:-_MAX_SESSION_TURNS]


def _session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _session_ref(session_id: str, generation: int) -> str:
    return f"sha256:{hashlib.sha256(f'{session_id}\0{generation}'.encode()).hexdigest()}"


def _principal_scope(user_id: str) -> str:
    return f"sha256:{hashlib.sha256(user_id.encode('utf-8')).hexdigest()}"


def _prior_turns_ref(session: ConversationSession, *, limit: int = 8) -> str:
    if not session.turns:
        return ""
    principal_scope = _principal_scope(session.user_id)
    session_ref = _session_ref(session.session_id, session.generation)
    material = [
        {
            "turn_index": turn.turn_index,
            "question_sha256": hashlib.sha256(turn.question.encode("utf-8")).hexdigest(),
            "answer_sha256": hashlib.sha256(
                repr(sorted(turn.answer.items())).encode("utf-8")
            ).hexdigest(),
        }
        for turn in session.turns[-limit:]
    ]
    digest = hashlib.sha256(repr((principal_scope, session_ref, material)).encode()).hexdigest()
    return f"bragi-prior-turns:{principal_scope}:{session_ref}:sha256:{digest}"


def _resource_type_from_proposal(judgment: SemanticJudgmentProposal | None) -> str:
    if judgment is None:
        return "unknown"
    for target in judgment.targets:
        if target.kind in {"object_type", "resource_type"}:
            return str(target.canonical_value or target.value)
    for target in judgment.targets:
        if target.kind == "resource":
            return "Resource"
    return "unknown"


def _session_sequence_key(session_id: str) -> str:
    return f"{_BRAGI_STATE_PREFIX}/session/{_session_digest(session_id)}/sequence"


def _intent_training_stage_key(
    *,
    contract_version: str,
    corpus_digest: str,
    candidate_digest: str,
    stage: str,
) -> str:
    key = stable_idempotency_key(
        "bragi-intent-training-stage",
        contract_version,
        corpus_digest,
        candidate_digest,
        stage,
    )
    return f"{_INTENT_TRAINING_EVIDENCE_PREFIX}{key}"


def _turn_outbox_key(session_ref: str, turn_index: int, generation: int | None = None) -> str:
    del generation
    digest = hashlib.sha256(session_ref.encode("utf-8")).hexdigest()
    return f"{_BRAGI_STATE_PREFIX}/turn-outbox/{digest}/{turn_index:020d}"


def _published_turn_outbox_tombstone(stored: Mapping[str, Any], *, revision: int) -> dict[str, Any]:
    payload = stored.get("payload")
    payload_digest = (
        _payload_digest(payload)
        if isinstance(payload, Mapping)
        else str(stored.get("payload_digest") or "")
    )
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "status": "published",
        "session_ref": str(stored.get("session_ref") or ""),
        "turn_index": int(stored.get("turn_index") or 0),
        "payload_digest": payload_digest,
        "retention_window": str(_TURN_OUTBOX_TOMBSTONE_RETENTION),
    }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"sha256:{digest}"


def _preference_from_index_row(row: Mapping[str, Any]) -> UserPreferenceRecord:
    updated_at_raw = row.get("updated_at")
    updated_at = datetime.fromisoformat(updated_at_raw) if isinstance(updated_at_raw, str) else None
    answer_intent_detail = row.get("answer_intent_detail")
    answer_intent_format = row.get("answer_intent_format")
    return UserPreferenceRecord(
        principal_id=str(row["principal_id"]),
        locale=str(row.get("locale") or "en"),
        verbosity=str(row.get("verbosity") or "concise"),
        answer_detail=str(row.get("answer_detail") or "standard"),
        answer_format=str(row.get("answer_format") or "prose"),
        answer_preferences_enabled=bool(row.get("answer_preferences_enabled", True)),
        answer_intent_detail=(
            dict(answer_intent_detail) if isinstance(answer_intent_detail, Mapping) else {}
        ),
        answer_intent_format=(
            dict(answer_intent_format) if isinstance(answer_intent_format, Mapping) else {}
        ),
        timezone=str(row["timezone"]) if isinstance(row.get("timezone"), str) else None,
        share_with_learner=bool(row.get("share_with_learner", False)),
        revision=int(row.get("revision", 0)),
        updated_at=updated_at,
    )


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession"]
