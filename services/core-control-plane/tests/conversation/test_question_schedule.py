"""Question campaign schedule and due-gate tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.question_perspectives import QuestionPerspective
from fdai.core.conversation.question_schedule import (
    QuestionCampaignPrerequisites,
    QuestionScheduleProfile,
    QuestionWorkloadPrincipalReceipt,
    evaluate_question_campaign_due,
)

NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _profile(*, enabled: bool = True) -> QuestionScheduleProfile:
    return QuestionScheduleProfile(
        profile_id="weekly-question-assurance",
        enabled=enabled,
        cron="0 2 * * 1",
        timezone="UTC",
        generation_profile="balanced-bilingual-v1",
        model_profile="question-generator-default",
        question_budget=20,
        time_budget_seconds=1_800,
        no_progress_seconds=300,
        token_budget=200_000,
        cost_budget_microusd=500_000,
        locales=("en", "ko"),
        perspectives=tuple(sorted(QuestionPerspective, key=lambda item: item.value)),
    )


def _ready() -> QuestionCampaignPrerequisites:
    return QuestionCampaignPrerequisites(
        previous_campaign_terminal=True,
        ontology_available=True,
        manifest_available=True,
        semantic_transport_ready=True,
        workload_principal=QuestionWorkloadPrincipalReceipt(
            principal_digest=DIGEST,
            role="reader",
            role_source="server-role-mapping",
            scope_digest=DIGEST,
            purpose="operations-review",
            authentication_evidence_digest=DIGEST,
            authenticated_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=30),
        ),
        generation_model_available=True,
        evidence_minimum_ready=True,
        budget_remaining=True,
        campaign_lock_available=True,
    )


def test_schedule_defaults_disabled_and_skips_before_readiness() -> None:
    decision = evaluate_question_campaign_due(
        profile=_profile(enabled=False),
        prerequisites=replace(_ready(), ontology_available=False),
        now=NOW,
        last_started_at=None,
    )

    assert decision.state == "skipped"
    assert decision.reason == "schedule_disabled"
    assert decision.execution_authority is False


def test_missing_reader_mapping_holds_before_model_work() -> None:
    principal = _ready().workload_principal
    assert principal is not None
    decision = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=replace(
            _ready(),
            workload_principal=replace(principal, role="operator"),
        ),
        now=NOW,
        last_started_at=None,
    )

    assert decision.state == "held"
    assert decision.reason == "scheduled_principal_reader_mapping_unavailable"


def test_missing_or_expired_workload_identity_holds_before_model_work() -> None:
    missing = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=replace(_ready(), workload_principal=None),
        now=NOW,
        last_started_at=None,
    )
    principal = _ready().workload_principal
    assert principal is not None
    expired = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=replace(
            _ready(),
            workload_principal=replace(principal, expires_at=NOW),
        ),
        now=NOW,
        last_started_at=None,
    )

    assert missing.reason == "scheduled_principal_unavailable"
    assert expired.reason == "scheduled_principal_reader_mapping_unavailable"


def test_workload_receipt_rejects_human_identity_kind() -> None:
    principal = _ready().workload_principal
    assert principal is not None
    with pytest.raises(ValueError, match="workload identity"):
        replace(principal, principal_kind="human")


def test_due_gate_requires_cron_bucket_and_all_prerequisites() -> None:
    not_due = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=_ready(),
        now=datetime(2026, 8, 24, 2, 1, tzinfo=UTC),
        last_started_at=None,
    )
    duplicate = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=_ready(),
        now=NOW,
        last_started_at=NOW,
    )
    due = evaluate_question_campaign_due(
        profile=_profile(),
        prerequisites=_ready(),
        now=NOW,
        last_started_at=None,
    )

    assert (not_due.state, not_due.reason) == ("skipped", "schedule_not_due")
    assert (duplicate.state, duplicate.reason) == ("skipped", "schedule_already_started")
    assert due.state == "due"
    assert due.due is True
