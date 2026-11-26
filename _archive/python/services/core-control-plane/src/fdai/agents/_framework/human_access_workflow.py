"""Fixed-owner execution handoffs on declared topics; references never grant authority.

Forseti judges, Var carries exact current human review, Muninn persists sealed
case effects, Thor dispatches and Heimdall independently observes. Saga appends
and seals; no agent calls another, changes its role or invokes a hot-path model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.human_access_workflow import (
    HUMAN_ACCESS_EVENT_TYPE,
    HUMAN_ACCESS_WORK_KIND,
    HumanAccessHandoff,
    HumanAccessWorkNotice,
)

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import Handler
from fdai.agents.thor import Thor
from fdai.core.human_assignment.execution_ports import HumanAccessAgentBindings


def owned_human_access_handler(agent: Agent, bindings: HumanAccessAgentBindings | None) -> Handler:
    """Wrap only declared subscribers, preserving normal unrelated messages unchanged."""

    async def handle(topic: str, payload: dict[str, Any]) -> None:
        is_notice = topic == "object.event" and payload.get("event_type") == HUMAN_ACCESS_EVENT_TYPE
        is_handoff = payload.get("kind") == HUMAN_ACCESS_WORK_KIND
        if not is_notice and not is_handoff:
            await agent.on_typed_message(topic, payload)
            return
        if agent.spec.name == "Saga":
            await agent.on_typed_message(topic, payload)
            return
        if is_notice:
            if payload.get("producer_principal") != "Huginn":
                raise ValueError("human access notice requires the Huginn-owned normalized Event")
            attributes = payload.get("attributes")
            if not isinstance(attributes, Mapping):
                raise ValueError("human access notice attributes are unavailable")
            notice = HumanAccessWorkNotice.model_validate(attributes.get("human_access_notice"))
            if payload.get("correlation_id") != str(notice.request_id):
                raise ValueError("human access notice correlation is inconsistent")
            if bindings is None:
                if agent.spec.name == "Forseti":
                    await _publish(
                        agent,
                        "object.verdict",
                        HumanAccessHandoff(
                            notice=notice, stage="held", reason="human_access_binding_unavailable"
                        ),
                    )
                return
            if agent.spec.name == "Forseti" and notice.operation in {
                "request",
                "decision",
                "resume",
            }:
                step = (
                    bindings.judge_request
                    if notice.operation == "request"
                    else bindings.resume
                    if notice.operation == "resume"
                    else bindings.judge_decision
                )
                if step is None:
                    raise ValueError("human access prepared recovery binding is unavailable")
                await _call_and_publish(agent, "object.verdict", notice, step)
            elif agent.spec.name == "Heimdall" and notice.operation in {"reconcile", "recovery"}:
                await _call_and_publish(agent, "object.drift", notice, bindings.observe_notice)
            return
        handoff = HumanAccessHandoff.model_validate(payload.get("human_access"))
        if payload.get("correlation_id") != str(handoff.notice.request_id):
            raise ValueError("human access handoff correlation is inconsistent")
        if bindings is None or handoff.stage == "held":
            return
        owner, stage = agent.spec.name, handoff.stage
        source = payload.get("producer_principal")
        if topic == "object.audit-entry":
            if source != "Saga":
                raise ValueError("human access state transition requires the Saga-owned seal")
            if owner == "Var" and stage in {
                "proposed",
                "decision_checked",
                "prepared",
                "recovery_proposed",
                "effect_recorded",
            }:
                await _call_and_publish(agent, "object.approval", handoff, bindings.review)
            elif owner == "Muninn" and stage == "human_reviewed":
                await _call_and_publish(agent, "object.state-snapshot", handoff, bindings.prepare)
            elif owner == "Muninn" and stage == "effect_checked":
                await _call_and_publish(
                    agent, "object.state-snapshot", handoff, bindings.record_effect
                )
            elif (
                owner == "Muninn"
                and stage == "effect_mismatch"
                and bindings.record_failure is not None
            ):
                await _call_and_publish(
                    agent, "object.state-snapshot", handoff, bindings.record_failure
                )
        elif owner == "Thor" and (
            (topic == "object.verdict" and stage == "recovery_judged" and source == "Forseti")
            or (topic == "object.approval" and stage == "recovery_verified" and source == "Var")
        ):
            # These are content-free recovery handoffs, never a provider dispatch or success claim.
            await _publish(agent, "object.action-run", handoff)
        elif (
            owner == "Vidar"
            and topic == "object.action-run"
            and stage in {"recovery_judged", "recovery_verified"}
        ):
            if source != "Thor":
                raise ValueError("human access recovery requires original Thor handoff")
            recovery_step = (
                bindings.propose_recovery
                if stage == "recovery_judged"
                else bindings.finish_recovery
            )
            if recovery_step is None:
                raise ValueError("human access recovery callback is unavailable")
            await _call_and_publish(agent, "object.rollback", handoff, recovery_step)
        elif owner == "Thor" and topic == "object.approval" and stage == "dispatch_ready":
            if source != "Var":
                raise ValueError("human access dispatch requires Var's exact current human quorum")
            if (
                not isinstance(agent, Thor)
                or agent._must_shadow()
                or not agent._saga_available
                or not agent._vidar_available
            ):
                await _publish(
                    agent,
                    "object.action-run",
                    HumanAccessHandoff(
                        notice=handoff.notice,
                        stage="held",
                        reason="human_access_thor_safety_unavailable",
                    ),
                )
                return
            await _call_and_publish(agent, "object.action-run", handoff, bindings.dispatch)
        elif owner == "Heimdall" and topic == "object.action-run" and stage == "dispatch_pending":
            if source != "Thor":
                raise ValueError("human access effect observation requires Thor dispatch lineage")
            await _call_and_publish(agent, "object.drift", handoff, bindings.observe)
        elif owner == "Forseti" and topic == "object.drift" and stage == "effect_observed":
            if source != "Heimdall":
                raise ValueError(
                    "human access effect judgment requires independent Heimdall evidence"
                )
            await _call_and_publish(agent, "object.verdict", handoff, bindings.judge_effect)
        elif owner == "Forseti" and topic == "object.drift" and stage == "recovery_observed":
            if source != "Heimdall" or bindings.judge_recovery is None:
                raise ValueError(
                    "human access recovery requires independently observed original evidence"
                )
            await _call_and_publish(agent, "object.verdict", handoff, bindings.judge_recovery)

    return handle


async def _call_and_publish(agent: Agent, topic: str, value: Any, step: Any) -> None:
    try:
        result = await step(value)
    except (ValueError, PermissionError):
        notice = value if isinstance(value, HumanAccessWorkNotice) else value.notice
        result = HumanAccessHandoff(
            notice=notice, stage="held", reason="human_access_current_evidence_held"
        )
    await _publish(agent, topic, result)


async def seal_human_access(agent: Agent, topic: str, payload: Mapping[str, Any]) -> None:
    """Saga validates owner/stage before emitting its audited immutable reference seal."""
    if topic == "object.audit-entry":
        return
    expected = {
        "object.verdict": (
            "Forseti",
            {
                "proposed",
                "decision_checked",
                "effect_checked",
                "effect_mismatch",
                "recovery_judged",
            },
        ),
        "object.approval": (
            "Var",
            {"awaiting_human", "human_reviewed", "dispatch_ready", "recovery_verified"},
        ),
        "object.state-snapshot": ("Muninn", {"prepared", "effect_recorded", "recovery_held"}),
        "object.action-run": (
            "Thor",
            {"dispatch_pending", "recovery_judged", "recovery_proposed", "recovery_verified"},
        ),
        "object.drift": ("Heimdall", {"effect_observed", "recovery_observed"}),
        "object.rollback": ("Vidar", {"recovery_proposed", "recovery_recorded"}),
    }
    if topic not in expected:
        return
    owner, stages = expected[topic]
    handoff = HumanAccessHandoff.model_validate(payload.get("human_access"))
    if payload.get("producer_principal") != owner or handoff.stage not in stages | {"held"}:
        raise ValueError("human access stage does not belong to its fixed owner")
    await _publish(agent, "object.audit-entry", handoff, audited_topic=topic)


async def _publish(
    agent: Agent, topic: str, handoff: HumanAccessHandoff, *, audited_topic: str | None = None
) -> None:
    if agent.bus is None:
        raise RuntimeError("human access owner bus is unavailable")
    body = {
        "kind": HUMAN_ACCESS_WORK_KIND,
        "schema_version": "1.0.0",
        "human_access": handoff.model_dump(mode="json"),
        "correlation_id": str(handoff.notice.request_id),
        "resource_id": "human-assignment:" + handoff.notice.case_id,
        "idempotency_key": f"human-access:{handoff.notice.request_id}:{topic}:{handoff.stage}",
        "execution_authority": False,
    }
    if audited_topic is not None:
        body["audited_topic"] = audited_topic
    await agent.bus.publish(agent.spec.name, topic, body)


__all__ = ["owned_human_access_handler", "seal_human_access"]
