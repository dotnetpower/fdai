"""Fixed-owner assignment command handoffs without direct peer calls or IAM authority."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fdai_service_contracts.assignment_transport import (
    AssignmentAgentDecision,
    AssignmentCaseResult,
    AssignmentRequestNotice,
)

from fdai.agents._framework.base import Agent

AssignmentClock = Callable[[], datetime]
AssignmentCheck = Callable[..., Awaitable[None]]
AssignmentIamRead = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


class AssignmentMaterializer(Protocol):
    """Muninn-only case writer; it has no PR publisher, directory writer, or executor."""

    async def apply(
        self, notice: AssignmentRequestNotice, *, at: datetime
    ) -> Mapping[str, object]: ...


def assignment_clock() -> datetime:
    """Return the explicit runtime clock used for fresh source checks at every stage."""
    return datetime.now(UTC)


class AssignmentJudgmentMixin:
    """Forseti's receipt-only assignment boundary, kept outside its general decision machinery."""

    def initialize_assignment_checks(self) -> None:
        """Create independent per-instance optional readers before the runtime binds them."""
        self._assignment_check: AssignmentCheck | None = None
        self._assignment_clock: AssignmentClock = assignment_clock
        self._assignment_iam_reader: AssignmentIamRead | None = None

    def bind_assignment_check(
        self, check: AssignmentCheck, *, clock: AssignmentClock = assignment_clock
    ) -> None:
        """Bind read-only receipt validation, never a case writer or executor."""
        self._assignment_check, self._assignment_clock = check, clock

    def bind_assignment_iam_reader(self, reader: AssignmentIamRead) -> None:
        """Bind exact ownership-effect reads; judgment remains shadow-ceiling HIL."""
        self._assignment_iam_reader = reader

    async def _assignment_message(self, topic: str, payload: dict[str, Any]) -> bool:
        """Consume only the exact assignment event types through their existing judged path."""
        if topic != "object.event":
            return False
        if payload.get("event_type") == "human.assignment.iam_apply_requested":
            await judge_iam_request(cast(Agent, self), payload, self._assignment_iam_reader)
            return True
        if payload.get("event_type") == "human.assignment.requested":
            await judge_assignment(
                cast(Agent, self), payload, self._assignment_check, clock=self._assignment_clock
            )
            return True
        return False


class AssignmentReviewMixin:
    """Var's independent review binding outside its approval machinery."""

    def initialize_assignment_review(self) -> None:
        self._assignment_check: AssignmentCheck | None = None
        self._assignment_clock: AssignmentClock = assignment_clock

    def bind_assignment_check(
        self, check: AssignmentCheck, *, clock: AssignmentClock = assignment_clock
    ) -> None:
        """Bind read-only human-review verification without case-write authority."""
        self._assignment_check, self._assignment_clock = check, clock

    async def _assignment_review_message(self, topic: str, payload: dict[str, Any]) -> bool:
        if topic != "object.audit-entry" or payload.get("kind") != "human_assignment":
            return False
        await review_assignment(
            cast(Agent, self),
            payload,
            self._assignment_check,
            clock=self._assignment_clock,
        )
        return True


async def judge_iam_request(
    agent: Agent, payload: Mapping[str, Any], reader: AssignmentIamRead | None
) -> None:
    """Forseti proposes only HIL or denial; no IAM event can raise the shadow ceiling."""
    if payload.get("producer_principal") != "Huginn":
        raise ValueError("IAM request requires a Huginn-owned event")
    attributes = payload.get("attributes")
    notice = attributes.get("iam_request") if isinstance(attributes, Mapping) else None
    if not isinstance(notice, Mapping) or reader is None:
        result: dict[str, Any] = {
            "risk_verdict": "deny",
            "reason": "assignment_iam_evidence_unavailable",
        }
    else:
        try:
            result = dict(await reader(notice))
        except ValueError:
            result = {"risk_verdict": "deny", "reason": "assignment_iam_evidence_mismatch"}
    if agent.bus is None:
        raise RuntimeError("IAM request judgment bus is unavailable")
    action_type = result.get("action_type", "ops.apply-human-access")
    if action_type not in {"ops.apply-human-access", "ops.revoke-human-access"}:
        action_type = "ops.apply-human-access"
        result = {"risk_verdict": "deny", "reason": "assignment_iam_evidence_mismatch"}
    await agent.bus.publish(
        agent.spec.name,
        "object.verdict",
        {
            "resource_id": payload.get("resource_id"),
            **result,
            "kind": "human_access_request",
            "correlation_id": payload.get("correlation_id"),
            "idempotency_key": payload.get("idempotency_key"),
            "event_id": payload.get("event_id"),
            "action_type": action_type,
            "resolved_autonomy_ceiling": "shadow_only",
            "execution_authority": False,
        },
    )


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
        or (
            decision.notice.operation != "assignments.review"
            and not (
                decision.notice.schema_version == "1.3.0"
                and decision.notice.operation == "assignments.confirm"
            )
        )
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
                reason=(
                    "human_confirmation_verified"
                    if decision.notice.operation == "assignments.confirm"
                    else "independent_review_verified"
                ),
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
    requires_human_seal = decision.notice.operation == "assignments.review" or (
        decision.notice.schema_version == "1.3.0"
        and decision.notice.operation == "assignments.confirm"
    )
    expected = (
        ("object.approval", "reviewed") if requires_human_seal else ("object.verdict", "validated")
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
    "AssignmentJudgmentMixin",
    "AssignmentIamRead",
    "assignment_clock",
    "judge_assignment",
    "judge_iam_request",
    "materialize_assignment",
    "review_assignment",
    "seal_assignment",
]
