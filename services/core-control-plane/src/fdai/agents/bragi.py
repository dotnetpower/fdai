"""Bragi translator over bounded structured semantic judgment.

Bragi maps an operator turn onto canonical Pantheon capabilities, gathers
read-only owned evidence, and renders the result. Candidate meaning never
grants execution authority; direct action requests re-enter the typed pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Awaitable, Callable, Collection, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bragi_ask_runtime import (
    _MAX_SESSIONS as _MAX_SESSIONS,
)
from fdai.agents._framework.bragi_ask_runtime import (
    BragiAskRuntimeMixin,
)
from fdai.agents._framework.bragi_contributors import (
    AnswerFn,
)
from fdai.agents._framework.bragi_conversation_runtime import BragiConversationRuntimeMixin
from fdai.agents._framework.bragi_intent_training import (
    IntentTrainingEvaluator,
    IntentTrainingEvidence,
    IntentTrainingRun,
    ReviewedIntentTrainingPromotion,
    build_unbound_training_payload,
    evaluate_training_contract,
)
from fdai.agents._framework.bragi_models import ConversationSession, RoutingDecision, Turn
from fdai.agents._framework.bragi_progress import record_progress
from fdai.agents._framework.bragi_publication import (
    BragiPublicationMixin,
)
from fdai.agents._framework.bragi_runtime_helpers import (
    _intent_training_stage_key as _intent_training_stage_key,
)
from fdai.agents._framework.bragi_runtime_helpers import (
    _locale_is_supported as _locale_is_supported,
)
from fdai.agents._framework.bragi_runtime_helpers import (
    _payload_digest as _payload_digest,
)
from fdai.agents._framework.bragi_runtime_helpers import (
    _turn_outbox_key as _turn_outbox_key,
)
from fdai.agents._framework.bragi_status_runtime import BragiStatusRuntimeMixin
from fdai.agents._framework.bragi_turn_runtime import BragiTurnRuntimeMixin
from fdai.agents._framework.deliberation import (
    ConversationDeliberator,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.semantic_routing import SemanticAgentRouter
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.metering.budget import BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink
from fdai.shared.providers.state_store import StateStore

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
class Bragi(
    BragiPublicationMixin,
    BragiConversationRuntimeMixin,
    BragiAskRuntimeMixin,
    BragiTurnRuntimeMixin,
    BragiStatusRuntimeMixin,
    Agent,
):
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
        self._state_store: StateStore | None = state_store
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

    # ---- action proposal (conversational-port re-entry, 7.7) -----------

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

    # ---- routing -------------------------------------------------------

    # ---- session -------------------------------------------------------


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession"]
