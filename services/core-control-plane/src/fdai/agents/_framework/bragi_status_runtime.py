"""Handoff, health, and introspection mixin for Bragi."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bragi_models import ConversationSession, Turn
from fdai.agents._framework.bragi_publication import handoff_event_payload
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.role_answers import bragi_role_answer
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger("fdai.agents.bragi")

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec
    from fdai.agents._framework.bragi_intent_training import IntentTrainingEvaluator


class BragiStatusRuntimeMixin:
    """Publish handoff outcomes and report Bragi state."""

    _clock: Callable[[], datetime]
    _sessions: dict[str, ConversationSession]
    spec: AgentSpec
    _turn_outbox_pending: int
    _last_preference_index_refresh: dict[str, Any] | None
    _intent_training_evaluator: IntentTrainingEvaluator | None
    _last_intent_training_retention: dict[str, Any]
    _last_intent_training: dict[str, Any] | None
    _a2a_turn_indexes: dict[tuple[str, str], int]

    if TYPE_CHECKING:

        async def publish_handoff_event(self, payload: dict[str, Any]) -> bool: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        def behavior_snapshot(self) -> dict[str, int]: ...

    _state_store: StateStore | None

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
