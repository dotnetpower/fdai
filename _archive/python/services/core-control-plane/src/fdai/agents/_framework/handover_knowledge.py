"""Fixed-agent handover source choreography on existing topics, never a catalog promotion path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from fdai_service_contracts.handover_knowledge import (
    KNOWLEDGE_KIND,
    KNOWLEDGE_SOURCE_EVENT,
    HandoverKnowledgeDecision,
    HandoverKnowledgeNotice,
)
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt

from fdai.agents._framework.base import Agent
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.core.human_assignment.knowledge_stage import HandoverKnowledgeStage
from fdai.shared.providers.handover_semantics import (
    HandoverSemanticCompiler,
    HandoverSemanticReviewer,
)


class _Learner(Protocol):
    _consensus: NornsConsensus
    _candidate_publication_gate: Callable[[], bool] | None


class _Steward(Protocol):
    _guard: CandidateGuard


class HandoverKnowledgeMixin:
    """An agent-owned typed handler with only its own optional source-check/materialization port."""

    _handover_stage: HandoverKnowledgeStage | None = None
    _handover_compiler: HandoverSemanticCompiler | None = None
    _handover_reviewer: HandoverSemanticReviewer | None = None

    def bind_handover_knowledge(self, stage: HandoverKnowledgeStage) -> None:
        """Bind one matching owner before subscriptions; no peer agent handle is accepted."""
        agent = cast(Agent, self)
        if stage.owner != agent.spec.name or self._handover_stage is not None:
            raise ValueError("handover stage binding does not match its sole owner")
        self._handover_stage = stage

    def bind_handover_compiler(self, compiler: HandoverSemanticCompiler) -> None:
        """Only Norns receives the off-path semantic extraction capability, never another agent."""
        if cast(Agent, self).spec.name != "Norns" or self._handover_compiler is not None:
            raise ValueError("semantic compiler belongs only to Norns")
        self._handover_compiler = compiler

    def bind_handover_reviewer(self, reviewer: HandoverSemanticReviewer) -> None:
        """Only Mimir receives independent deterministic package readback, with no model port."""
        if cast(Agent, self).spec.name != "Mimir" or self._handover_reviewer is not None:
            raise ValueError("semantic reviewer belongs only to Mimir")
        self._handover_reviewer = reviewer

    async def _handover_message(self, topic: str, payload: dict[str, Any]) -> bool:
        """Return whether this exact no-action workflow consumed the typed message."""
        agent = cast(Agent, self)
        name = agent.spec.name
        if (
            name == "Forseti"
            and topic == "object.event"
            and payload.get("event_type") == KNOWLEDGE_SOURCE_EVENT
        ):
            if payload.get("producer_principal") != "Huginn":
                raise ValueError("handover source notice requires Huginn ingress")
            attributes = payload.get("attributes")
            raw = attributes.get("knowledge_notice") if isinstance(attributes, dict) else None
            notice = HandoverKnowledgeNotice.model_validate(raw)
            _correlate(payload, notice)
            decision = await _check(self._handover_stage, notice)
            if self._handover_stage is not None:
                decision = await self._handover_stage.record(decision)
            await _publish(agent, "object.verdict", decision)
            if decision.disposition == "conflict":
                await _publish(agent, "object.arbitration-request", decision)
            return True
        if payload.get("kind") != KNOWLEDGE_KIND:
            return False
        if name == "Saga":
            await _seal(agent, topic, payload)
            return True
        if name == "Odin":
            if topic == "object.arbitration-request":
                decision = _owned(payload, "Forseti")
                if decision.disposition != "conflict":
                    raise ValueError("handover arbitration requires an explicit evidence conflict")
                await _publish(
                    agent,
                    "object.arbitration-decision",
                    decision.model_copy(update={"reason": "clarification_required"}),
                )
            return True
        if name == "Forseti":
            # Odin's disposition is sealed by Saga; there is no second generic action verdict.
            return True
        if name == "Muninn":
            if topic != "object.audit-entry" or payload.get("audited_topic") not in {
                "object.verdict",
                "object.arbitration-decision",
            }:
                return True
            decision = _owned(payload, "Saga")
            if (
                decision.disposition == "conflict"
                and payload.get("audited_topic") != "object.arbitration-decision"
            ):
                return True
            decision = await _recheck(self._handover_stage, decision)
            await _publish(agent, "object.state-snapshot", decision)
            return True
        if name == "Norns":
            if (
                topic != "object.audit-entry"
                or payload.get("audited_topic") != "object.state-snapshot"
            ):
                return True
            decision = await _recheck(self._handover_stage, _owned(payload, "Saga"))
            await _propose(agent, decision)
            return True
        if name == "Mimir":
            if topic != "object.rule-candidate":
                return True
            semantic = None
            decision = await _recheck(self._handover_stage, _owned(payload, "Norns"), persist=False)
            if self._handover_reviewer is not None:
                try:
                    await self._handover_reviewer.maintain(
                        decision.notice, withdrawn=decision.disposition == "withdrawn"
                    )
                except Exception:  # noqa: BLE001 - retention failures expose no source text.
                    decision = _held(decision.notice, "source_unavailable")
            if decision.disposition == "admitted":
                consensus = payload.get("norns_consensus")
                if (
                    not isinstance(consensus, dict)
                    or consensus != NornsConsensus().evaluate(_candidate(decision)).summary()
                ):
                    decision = _held(decision.notice, "publication_held")
                elif (
                    self._handover_stage is not None
                    and not await self._handover_stage.already_recorded(decision)
                    and not cast(_Steward, agent)._guard.inspect(_candidate(decision)).accepted
                ):
                    decision = _held(decision.notice, "publication_held")
            if decision.disposition == "admitted" and payload.get("semantic") is not None:
                try:
                    if self._handover_reviewer is None:
                        raise ValueError("semantic reviewer is unavailable")
                    semantic = await self._handover_reviewer.review(
                        decision.notice, HandoverSemanticReceipt.model_validate(payload["semantic"])
                    )
                except Exception:  # noqa: BLE001 - no source or provider error text enters the bus.
                    decision = _held(decision.notice, "source_unavailable")
            if self._handover_stage is not None:
                decision = await self._handover_stage.record(decision)
            # Packages stay private and inert; only independently verified references leave.
            await _publish(agent, "object.rule", decision, semantic=semantic)
            return True
        return False


async def _check(
    stage: HandoverKnowledgeStage | None, notice: HandoverKnowledgeNotice
) -> HandoverKnowledgeDecision:
    return await stage.check(notice) if stage is not None else _held(notice, "binding_unavailable")


async def _recheck(
    stage: HandoverKnowledgeStage | None,
    decision: HandoverKnowledgeDecision,
    *,
    persist: bool = True,
) -> HandoverKnowledgeDecision:
    if stage is None:
        return _held(decision.notice, "binding_unavailable")
    latest = await stage.check(decision.notice)
    # Earlier negative owner evidence can only be replaced by a new source notice.
    if decision.disposition == "admitted" or latest.disposition == "withdrawn":
        decision = latest
    return await stage.record(decision) if persist else decision


async def _propose(agent: Agent, decision: HandoverKnowledgeDecision) -> None:
    learner = cast(_Learner, agent)
    if decision.disposition == "admitted":
        if (
            learner._candidate_publication_gate is not None
            and not learner._candidate_publication_gate()
        ):
            decision = _held(decision.notice, "publication_held")
        else:
            consensus = learner._consensus.evaluate(_candidate(decision))
            if consensus.unanimous:
                body = _body(decision)
                body["norns_consensus"] = consensus.summary()
                compiler = cast(HandoverKnowledgeMixin, agent)._handover_compiler
                if compiler is not None:
                    try:
                        semantic = await compiler.compile(decision.notice)
                    except Exception:  # noqa: BLE001 - retain only content-free unavailability.
                        decision = _held(decision.notice, "source_unavailable")
                    else:
                        body["semantic"] = semantic.model_dump(mode="json")
                if decision.disposition != "admitted":
                    await _publish(agent, "object.rule-candidate", decision)
                    return
                if await agent._publish_proposal("object.rule-candidate", body):
                    agent.record_behavior("handover_knowledge:proposed")
                    return
            decision = _held(decision.notice, "publication_held")
    # Withdrawal/hold is a safety disposition, not discretionary positive proposal capacity.
    await _publish(agent, "object.rule-candidate", decision)


def _candidate(decision: HandoverKnowledgeDecision) -> dict[str, Any]:
    return {
        "proposed_by": "Norns",
        "proposal_kind": "new",
        "source_signal": "handover_knowledge",
        "target_rule_id": decision.notice.source_id,
        "evidence": {"source_digest": decision.notice.source_digest},
        "may_promote": False,
        "enforcement_mode": "shadow",
    }


async def _seal(agent: Agent, topic: str, payload: dict[str, Any]) -> None:
    owners = {
        "object.verdict": "Forseti",
        "object.arbitration-decision": "Odin",
        "object.state-snapshot": "Muninn",
        "object.rule": "Mimir",
    }
    if topic not in owners:
        raise ValueError("handover decision uses an unsupported audited owner topic")
    decision = _owned(payload, owners[topic])
    semantic = (
        HandoverSemanticReceipt.model_validate(payload["semantic"])
        if topic == "object.rule" and payload.get("semantic") is not None
        else None
    )
    await _publish(agent, "object.audit-entry", decision, audited_topic=topic, semantic=semantic)


def _owned(payload: dict[str, Any], owner: str) -> HandoverKnowledgeDecision:
    if payload.get("producer_principal") != owner:
        raise ValueError("handover knowledge message does not match its topic owner")
    decision = HandoverKnowledgeDecision.model_validate(payload.get("knowledge"))
    _correlate(payload, decision.notice)
    return decision


def _correlate(payload: dict[str, Any], notice: HandoverKnowledgeNotice) -> None:
    if payload.get("correlation_id") != notice.source_id:
        raise ValueError("handover knowledge correlation does not match its source namespace")


def _held(notice: HandoverKnowledgeNotice, reason: str) -> HandoverKnowledgeDecision:
    return HandoverKnowledgeDecision.model_validate(
        {"notice": notice, "disposition": "held", "reason": reason}
    )


def _body(decision: HandoverKnowledgeDecision) -> dict[str, Any]:
    return {
        "kind": KNOWLEDGE_KIND,
        "schema_version": "1.0.0",
        "correlation_id": decision.notice.source_id,
        "resource_id": f"handover-source:{decision.notice.source_id}",
        "idempotency_key": f"handover-knowledge:{decision.notice.notice_id}:{decision.disposition}",
        "knowledge": decision.model_dump(mode="json"),
        "execution_authority": False,
        "may_promote": False,
    }


async def _publish(
    agent: Agent,
    topic: str,
    decision: HandoverKnowledgeDecision,
    *,
    audited_topic: str | None = None,
    semantic: HandoverSemanticReceipt | None = None,
) -> None:
    if agent.bus is None:
        raise RuntimeError("handover owner event bus is unavailable")
    body = _body(decision)
    if audited_topic is not None:
        body["audited_topic"] = audited_topic
    if semantic is not None:
        body["semantic"] = semantic.model_dump(mode="json")
    await agent.bus.publish(agent.spec.name, topic, body)
    agent.record_behavior(f"handover_knowledge:{decision.disposition}")


__all__ = ["HandoverKnowledgeMixin"]
