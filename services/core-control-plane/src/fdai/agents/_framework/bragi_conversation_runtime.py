# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc,has-type"
"""Conversation routing and deliberation mixin for Bragi."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.agents._framework.bragi_contributors import normalize_responder_answer
from fdai.agents._framework.bragi_models import RoutingDecision
from fdai.agents._framework.bragi_progress import append_submitted
from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bragi_routing import route_semantic_judgment, semantic_capabilities
from fdai.agents._framework.bragi_runtime_helpers import (
    _locale_is_supported,
    _validate_question,
)
from fdai.agents._framework.pantheon import PANTHEON_NAMES

_LOG = logging.getLogger(__name__)
_MAX_PROGRESS_KEYS = 5_000
_MAX_CONTRIBUTORS = 2


class BragiConversationRuntimeMixin:
    """Route operator turns and deliberation without executor authority."""

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
