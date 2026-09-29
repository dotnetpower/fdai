"""Operator proposal binding tests for automation blueprint review."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.conversation import CreateScheduledTaskCommand, Principal, Role
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintAggregator,
    AutomationBlueprintEvidence,
    AutomationBlueprintReviewService,
    AutomationBlueprintState,
    BlueprintEvidenceSource,
    BlueprintOutcome,
    InMemoryAutomationBlueprintStore,
)
from fdai.core.scheduler.blueprints.proposals import (
    AutomationBlueprintProposalProcessor,
    AutomationBlueprintReviewProposal,
    ProposalRolePrincipalResolver,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile
from fdai.core.scheduler.store import InMemoryScheduleStore

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class _Authorizer:
    def can_review(self, principal: Principal) -> bool:
        return principal.role in {Role.APPROVER, Role.OWNER}


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


def _candidate():  # type: ignore[no-untyped-def]
    evidence = [
        AutomationBlueprintEvidence(
            evidence_id=f"turn-{index}",
            principal_id="operator-1",
            normalized_task_intent="check inventory drift",
            schedule_class="daily",
            schedule_expression="0 3 * * *",
            event_type="object.drift-check-requested",
            resource_scope="scope://subscription/example/resource-group/app",
            delivery_intent="audit-only",
            required_tools=("query_inventory",),
            isolation_profile=ScheduledRunIsolationProfile(),
            outcome=BlueprintOutcome.SUCCEEDED,
            source=BlueprintEvidenceSource.OPERATOR_TURN,
            occurred_at=_NOW + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    return AutomationBlueprintAggregator().aggregate(evidence, now=_NOW)[0]


def _processor() -> tuple[AutomationBlueprintProposalProcessor, InMemoryAutomationBlueprintStore]:
    store = InMemoryAutomationBlueprintStore()
    review = AutomationBlueprintReviewService(
        store=store,
        authorizer=_Authorizer(),
        audit=_Audit(),
        schedule_command=CreateScheduledTaskCommand(store=InMemoryScheduleStore()),
    )
    return (
        AutomationBlueprintProposalProcessor(
            review=review,
            principal_resolver=ProposalRolePrincipalResolver(),
        ),
        store,
    )


def _proposal(
    operation: str,
    candidate_id: str,
    *,
    roles: tuple[str, ...] = ("Approver",),
    reason: str = "recurring and bounded",
) -> AutomationBlueprintReviewProposal:
    payload: dict[str, object] = {"candidate_id": candidate_id}
    if operation != "automation_blueprint.materialize":
        payload["reason"] = reason
    return AutomationBlueprintReviewProposal(
        operation=operation,
        principal_id="approver-1",
        idempotency_key=f"idem-{operation}",
        payload=payload,
        principal_roles=roles,
    )


async def test_authorized_accept_proposal_reaches_candidate_store() -> None:
    processor, store = _processor()
    candidate = await store.create(_candidate())

    accepted = await processor.apply(
        _proposal("automation_blueprint.accept", candidate.candidate_id),
        at=_NOW + timedelta(days=1),
    )

    assert accepted.state is AutomationBlueprintState.ACCEPTED
    assert (await store.get(candidate.candidate_id)).reviewed_by == "approver-1"


async def test_unauthorized_stale_conflicting_and_duplicate_proposals_are_bounded() -> None:
    processor, store = _processor()
    candidate = await store.create(_candidate())

    with pytest.raises(PermissionError, match="not authorized|no ordinary"):
        await processor.apply(
            _proposal("automation_blueprint.accept", candidate.candidate_id, roles=("Reader",)),
            at=_NOW + timedelta(days=1),
        )

    accepted = await processor.apply(
        _proposal("automation_blueprint.accept", candidate.candidate_id),
        at=_NOW + timedelta(days=1),
    )
    duplicate = await processor.apply(
        _proposal("automation_blueprint.accept", candidate.candidate_id),
        at=_NOW + timedelta(days=2),
    )
    assert duplicate == accepted

    with pytest.raises(ValueError, match="only a draft"):
        await processor.apply(
            _proposal("automation_blueprint.reject", candidate.candidate_id),
            at=_NOW + timedelta(days=2),
        )

    expired = await store.create(
        AutomationBlueprintAggregator().aggregate(
            [
                AutomationBlueprintEvidence(
                    evidence_id=f"old-{index}",
                    principal_id="operator-1",
                    normalized_task_intent="check backup drift",
                    schedule_class="daily",
                    schedule_expression="0 4 * * *",
                    event_type="object.drift-check-requested",
                    resource_scope="scope://subscription/example/resource-group/backup",
                    delivery_intent="audit-only",
                    required_tools=("query_inventory",),
                    isolation_profile=ScheduledRunIsolationProfile(),
                    outcome=BlueprintOutcome.SUCCEEDED,
                    source=BlueprintEvidenceSource.OPERATOR_TURN,
                    occurred_at=_NOW + timedelta(minutes=index),
                )
                for index in range(3)
            ],
            now=_NOW - timedelta(days=40),
        )[0]
    )
    with pytest.raises(ValueError, match="expired"):
        await processor.apply(
            _proposal("automation_blueprint.accept", expired.candidate_id),
            at=_NOW,
        )
