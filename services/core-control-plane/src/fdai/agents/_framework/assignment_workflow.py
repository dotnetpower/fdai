"""Fixed-owner assignment command handoffs without direct peer calls or IAM authority."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.assignment_transport import (
    AssignmentAgentDecision,
    AssignmentCaseResult,
    AssignmentRequestNotice,
)

from fdai.agents._framework.base import Agent

AssignmentClock = Callable[[], datetime]
AssignmentCheck = Callable[..., Awaitable[None]]


class AssignmentMaterializer(Protocol):
    """Muninn-only case writer; it has no PR publisher, directory writer, or executor."""

    async def apply(
        self, notice: AssignmentRequestNotice, *, at: datetime
    ) -> Mapping[str, object]: ...


def assignment_clock() -> datetime:
    """Return the explicit runtime clock used for fresh source checks at every stage."""
    return datetime.now(UTC)


async def judge_assignment(
    agent: Agent,
    payload: Mapping[str, Any],
    check: AssignmentCheck | None,
    *,
    clock: AssignmentClock,
) -> None:
    """Forseti alone validates Huginn's notice before emitting a non-action Verdict."""
    if payload.get("producer_principal") != "Huginn":
        raise ValueError("assignment intake requires the Huginn-owned event")
    attributes = payload.get("attributes")
    if not isinstance(attributes, Mapping):
        raise ValueError("assignment event attributes are unavailable")
    notice = AssignmentRequestNotice.model_validate(attributes.get("assignment_notice"))
    _correlate(payload, notice)
    decision = AssignmentAgentDecision(
        notice=notice, disposition="held", reason="agent_binding_unavailable"
    )
    if check is not None:
        try:
            await check(notice, at=clock())
        except (PermissionError, ValueError):
            decision = AssignmentAgentDecision(
                notice=notice, disposition="held", reason="command_held"
            )
        else:
            decision = AssignmentAgentDecision(
                notice=notice, disposition="validated", reason="command_validated"
            )
    await _publish(agent, "object.verdict", decision)


async def review_assignment(
    agent: Agent,
    payload: Mapping[str, Any],
    check: AssignmentCheck | None,
    *,
    clock: AssignmentClock,
) -> None:
    """Var carries only the exact independent human review after Saga seals validation."""
    decision = _sealed(payload)
    if (
        payload.get("audited_topic") != "object.verdict"
        or decision.disposition != "validated"
        or decision.notice.operation != "assignments.review"
    ):
        return
    reviewed = AssignmentAgentDecision(
        notice=decision.notice, disposition="held", reason="agent_binding_unavailable"
    )
    if check is not None:
        try:
            await check(decision.notice, at=clock())
        except (PermissionError, ValueError):
            reviewed = AssignmentAgentDecision(
                notice=decision.notice, disposition="held", reason="review_held"
            )
        else:
            reviewed = AssignmentAgentDecision(
                notice=decision.notice,
                disposition="reviewed",
                reason="independent_review_verified",
            )
    await _publish(agent, "object.approval", reviewed)


async def materialize_assignment(
    agent: Agent,
    payload: Mapping[str, Any],
    materializer: AssignmentMaterializer | None,
    *,
    clock: AssignmentClock,
) -> None:
    """Muninn applies only the matching Saga seal, then emits its owned StateSnapshot."""
    decision = _sealed(payload)
    expected = (
        ("object.approval", "reviewed")
        if decision.notice.operation == "assignments.review"
        else ("object.verdict", "validated")
    )
    if (payload.get("audited_topic"), decision.disposition) != expected:
        return
    materialized = AssignmentAgentDecision(
        notice=decision.notice, disposition="held", reason="agent_binding_unavailable"
    )
    if materializer is not None:
        try:
            result = await materializer.apply(decision.notice, at=clock())
            parsed = AssignmentCaseResult.model_validate(result)
        except (PermissionError, ValueError):
            materialized = AssignmentAgentDecision(
                notice=decision.notice, disposition="held", reason="materialization_held"
            )
        else:
            materialized = AssignmentAgentDecision(
                notice=decision.notice,
                disposition="materialized",
                reason="case_materialized",
                result=parsed,
            )
    await _publish(agent, "object.state-snapshot", materialized)


async def seal_assignment(agent: Agent, topic: str, payload: Mapping[str, Any]) -> None:
    """Saga forwards a validated owner disposition only after its append-only audit succeeds."""
    expected = {
        "object.verdict": ("Forseti", {"validated", "held"}),
        "object.approval": ("Var", {"reviewed", "held"}),
        "object.state-snapshot": ("Muninn", {"materialized", "held"}),
    }
    if topic not in expected:
        raise ValueError("assignment decision uses an unsupported owner topic")
    owner, dispositions = expected[topic]
    if payload.get("producer_principal") != owner:
        raise ValueError("assignment decision does not match its topic owner")
    decision = AssignmentAgentDecision.model_validate(payload.get("assignment"))
    _correlate(payload, decision.notice)
    if decision.disposition not in dispositions:
        raise ValueError("assignment disposition does not belong to its owner")
    await _publish(agent, "object.audit-entry", decision, audited_topic=topic)


def _sealed(payload: Mapping[str, Any]) -> AssignmentAgentDecision:
    if payload.get("producer_principal") != "Saga":
        raise ValueError("assignment materialization requires a Saga-owned seal")
    decision = AssignmentAgentDecision.model_validate(payload.get("assignment"))
    _correlate(payload, decision.notice)
    return decision


def _correlate(payload: Mapping[str, Any], notice: AssignmentRequestNotice) -> None:
    if payload.get("correlation_id") != notice.case_id:
        raise ValueError("assignment event correlation does not match its case")


async def _publish(
    agent: Agent,
    topic: str,
    decision: AssignmentAgentDecision,
    *,
    audited_topic: str | None = None,
) -> None:
    if agent.bus is None:
        raise RuntimeError("assignment agent bus is unavailable")
    body: dict[str, Any] = {
        "kind": "human_assignment",
        "schema_version": "1.0.0",
        "correlation_id": decision.notice.case_id,
        "idempotency_key": (
            f"assignment:{decision.notice.proposal_id}:{topic}:{audited_topic or ''}"
        ),
        "assignment": decision.model_dump(mode="json"),
        "execution_authority": False,
    }
    if audited_topic is not None:
        body["audited_topic"] = audited_topic
    await agent.bus.publish(agent.spec.name, topic, body)
    agent.record_behavior(f"assignment:{decision.disposition}")


__all__ = [
    "AssignmentCheck",
    "AssignmentClock",
    "AssignmentMaterializer",
    "assignment_clock",
    "judge_assignment",
    "materialize_assignment",
    "review_assignment",
    "seal_assignment",
]
