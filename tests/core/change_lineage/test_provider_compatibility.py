"""Compatibility of live ChangeFeed adapters with canonical Change lineage."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from fdai.core.change_lineage import (
    ChangeLineageRecord,
    build_change_lineage,
    extract_learning_candidate,
)
from fdai.core.decision_case import (
    ActionOption,
    DecisionCase,
    DecisionSelection,
    ObjectiveEffect,
)
from fdai.core.impact_analysis import AffectedSet, ChangeAssessment
from fdai.delivery.azure_devops.change_feed import (
    AzureDevOpsChangeFeed,
    AzureDevOpsChangeFeedConfig,
)
from fdai.delivery.github.change_feed import GitHubChangeFeed, GitHubChangeFeedConfig
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.providers.change_feed import ChangeRecord

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
ACTION_ID = UUID("00000000-0000-0000-0000-000000000301")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000302")
OUTCOME_ID = UUID("00000000-0000-0000-0000-000000000303")


async def _token() -> str:
    return "test-token"  # noqa: S105 - synthetic credential used only by MockTransport


def _build_lineage(change: ChangeRecord) -> ChangeLineageRecord:
    affected = AffectedSet(
        direct_targets=("resource:one",),
        runtime_dependents=(),
        protected_services=("service:one",),
        protected_objectives=("objective:availability",),
        control_dependencies=(),
        graph_revision="graph:one",
    )
    assessment = ChangeAssessment(
        change_id=change.change_id,
        correlation_id="correlation:one",
        target_ref="resource:one",
        occurred_at=change.at,
        affected_set=affected,
        review_required=False,
        reasons=(),
        evidence_digest="a" * 64,
    )
    effect = ObjectiveEffect(
        objective_id="objective:availability",
        utility=0.8,
        confidence=0.9,
        metric="availability",
        expected_min=0.99,
        expected_max=1.0,
        observation_window_seconds=300,
    )
    option = ActionOption(
        option_id="option:scale",
        action_type="ops.scale-out",
        effects=(effect,),
        evidence_refs=("evidence:option",),
    )
    decision_case = DecisionCase(
        case_id="decision:one",
        correlation_id=assessment.correlation_id,
        context_snapshot_id="context:one",
        created_at=change.at + timedelta(seconds=1),
        no_action_effects=(replace(effect, utility=-0.8),),
        options=(option,),
        protected_objective_ids=(effect.objective_id,),
        active_constraint_ids=("constraint:one",),
        evidence_refs=("evidence:decision",),
    )
    selection = DecisionSelection(
        selected_option_id=option.option_id,
        objective_scores=((option.option_id, 0.8),),
        margin=0.8,
        requires_human_approval=False,
        reason="selected",
    )
    action = Action(
        schema_version="1.0.0",
        action_id=ACTION_ID,
        idempotency_key="action:provider-compatibility",
        event_id=EVENT_ID,
        action_type="ops.scale-out",
        target_resource_ref=assessment.target_ref,
        operation=Operation.SCALE,
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback:one"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.SHADOW,
        citing_rules=["rule:scale"],
        created_at=change.at + timedelta(seconds=2),
    )
    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=OUTCOME_ID,
        idempotency_key="outcome:provider-compatibility",
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest=hashlib.sha256(action.target_resource_ref.encode()).hexdigest(),
        label=ResponseOutcomeLabel.UNSCORABLE,
        verification_status=ResponseVerificationStatus.HOLD,
        verification_reason="shadow_only",
        execution_mode=action.mode,
        execution_outcome="shadowed",
        decision="auto",
        evidence_refs=("evidence:outcome",),
        recorded_at=change.at + timedelta(seconds=3),
    )
    return build_change_lineage(
        change=change,
        assessment=assessment,
        decision_case=decision_case,
        selection=selection,
        action=action,
        outcome=outcome,
    )


@pytest.mark.asyncio
async def test_github_change_feed_builds_canonical_lineage_candidate() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 41,
                    "sha": "abcdef1234567890",
                    "environment": "production",
                    "created_at": NOW.isoformat(),
                    "description": "release 41",
                    "creator": {"login": "deployer"},
                }
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = GitHubChangeFeed(
        config=GitHubChangeFeedConfig(repository="acme/app"),
        http_client=client,
        token_provider=_token,
    )
    try:
        records = await feed.recent(
            since=NOW - timedelta(minutes=1),
            until=NOW + timedelta(minutes=1),
            resource_hint="resource:one",
        )
    finally:
        await client.aclose()

    lineage = _build_lineage(records[0])
    candidate = extract_learning_candidate(lineage)

    assert lineage.change_source == candidate.change_source == "github"
    assert lineage.change_ref == candidate.change_ref == "abcdef123456"
    assert candidate.requires_sealed_case is True
    assert candidate.operational_reuse_eligible is False


@pytest.mark.asyncio
async def test_azure_devops_change_feed_builds_canonical_lineage_candidate() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": 42,
                        "buildNumber": "2026.42",
                        "sourceVersion": "fedcba6543217890",
                        "sourceBranch": "refs/heads/main",
                        "finishTime": NOW.isoformat(),
                        "requestedFor": {"displayName": "Deployer"},
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = AzureDevOpsChangeFeed(
        config=AzureDevOpsChangeFeedConfig(organization="acme", project="platform"),
        http_client=client,
        token_provider=_token,
    )
    try:
        records = await feed.recent(
            since=NOW - timedelta(minutes=1),
            until=NOW + timedelta(minutes=1),
            resource_hint="resource:one",
        )
    finally:
        await client.aclose()

    lineage = _build_lineage(records[0])
    candidate = extract_learning_candidate(lineage)

    assert lineage.change_source == candidate.change_source == "azure-devops"
    assert lineage.change_ref == candidate.change_ref == "fedcba654321"
    assert candidate.requires_sealed_case is True
    assert candidate.operational_reuse_eligible is False
