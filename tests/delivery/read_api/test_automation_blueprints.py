"""Automation blueprint read panel and ChatOps review API tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation import CreateScheduledTaskCommand, Principal, Role
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintAggregator,
    AutomationBlueprintCandidate,
    AutomationBlueprintEvidence,
    AutomationBlueprintReviewService,
    BlueprintEvidenceSource,
    BlueprintOutcome,
    InMemoryAutomationBlueprintStore,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.read_api.routes.automation_blueprints import (
    AutomationBlueprintPanel,
    make_automation_blueprint_review_routes,
)

_NOW = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)


class _Authorizer:
    def can_review(self, principal: Principal) -> bool:
        return principal.role is Role.APPROVER


class _Audit:
    async def append(self, event: Mapping[str, Any]) -> None:
        del event


async def _principal(_request: Request) -> Principal:
    return Principal(id="approver-1", role=Role.APPROVER)


def _candidate() -> AutomationBlueprintCandidate:
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
            estimated_cost_microusd=100,
        )
        for index in range(3)
    ]
    return AutomationBlueprintAggregator().aggregate(evidence, now=_NOW + timedelta(days=1))[0]


async def test_read_panel_shows_evidence_cost_scope_tools_isolation_and_metrics() -> None:
    store = InMemoryAutomationBlueprintStore()
    await store.create(_candidate())

    payload = await AutomationBlueprintPanel(store).render(params={})

    assert payload["mutation_controls"] is False
    card = payload["candidates"][0]
    assert len(card["evidence_fingerprints"]) == 3
    assert card["estimated_cost_microusd"] == 100
    assert card["resource_scope"].endswith("/app")
    assert card["required_tools"] == ["query_inventory"]
    assert card["isolation_profile"]["max_tool_calls"] == 0
    assert payload["metrics"]["proposed"] == 1


def test_chatops_review_and_materialize_routes_are_separate_from_panel() -> None:
    store = InMemoryAutomationBlueprintStore()
    schedules = InMemoryScheduleStore()
    service = AutomationBlueprintReviewService(
        store=store,
        authorizer=_Authorizer(),
        audit=_Audit(),
        schedule_command=CreateScheduledTaskCommand(store=schedules),
    )

    candidate_id = _candidate().candidate_id
    asyncio.run(service.submit(_candidate()))
    app = Starlette(
        routes=list(make_automation_blueprint_review_routes(service=service, authorize=_principal)),
    )
    with TestClient(app) as client:
        accepted = client.post(
            f"/automation-blueprints/{candidate_id}/review",
            json={"decision": "accept", "reason": "stable evidence"},
        )
        materialized = client.post(f"/automation-blueprints/{candidate_id}/materialize")

    assert accepted.status_code == 200
    assert accepted.json()["state"] == "accepted"
    assert materialized.status_code == 200
    assert materialized.json()["state"] == "materialized"
