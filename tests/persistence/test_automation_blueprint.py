"""Automation blueprint PostgreSQL store codec and live integration tests."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fdai.core.scheduler.blueprints import (
    AutomationBlueprintAggregator,
    AutomationBlueprintCandidate,
    AutomationBlueprintEvidence,
    AutomationBlueprintState,
    BlueprintEvidenceSource,
    BlueprintOutcome,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile
from fdai.delivery.persistence.postgres_automation_blueprint import (
    PostgresAutomationBlueprintStore,
    PostgresAutomationBlueprintStoreConfig,
    _row_to_candidate,
    _values,
)

_NOW = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def _candidate(*, suffix: str = "") -> AutomationBlueprintCandidate:
    evidence = [
        AutomationBlueprintEvidence(
            evidence_id=f"turn-{index}{suffix}",
            principal_id="principal-1",
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
    return AutomationBlueprintAggregator().aggregate(evidence, now=_NOW + timedelta(days=1))[0]


def test_blueprint_row_codec_round_trips_candidate() -> None:
    candidate = _candidate()
    columns = (
        "candidate_id dedup_key normalized_task_intent schedule_class schedule_expression "
        "event_type principal_id resource_scope delivery_intent required_tools isolation_profile "
        "estimated_cost_microusd evidence_fingerprints proposer confidence created_at expires_at "
        "state enabled shadow_only mutation_tool_ids reviewed_by review_reason resulting_task_id"
        " realized_usage_count"
    ).split()
    row = dict(zip(columns, _values(candidate), strict=True))

    assert _row_to_candidate(row) == candidate


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_postgres_blueprint_store_persists_and_cas_transitions() -> None:
    store = PostgresAutomationBlueprintStore(
        config=PostgresAutomationBlueprintStoreConfig(dsn=os.environ["FDAI_DATABASE_URL"])
    )
    candidate = _candidate(suffix=uuid4().hex[:8])
    stored = await store.create(candidate)
    assert stored == candidate
    accepted = await store.transition(
        replace(
            candidate,
            state=AutomationBlueprintState.ACCEPTED,
            reviewed_by="approver-1",
            review_reason="stable recurrence",
        ),
        expected_state=AutomationBlueprintState.DRAFT,
    )
    assert accepted is not None and accepted.state is AutomationBlueprintState.ACCEPTED
