"""Focused tests for conversation assurance persistence."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    AssuranceDecision,
    AssuranceVerdict,
    ChatPolicyCandidate,
    ChatPolicyTarget,
    DisputeReason,
    DisputeRecord,
    PolicyStage,
    PolicyTransition,
)
from fdai.delivery.persistence import (
    PostgresConversationAssuranceLedger,
    PostgresConversationAssuranceLedgerConfig,
    PostgresConversationPolicyCandidateStore,
    PostgresConversationPolicyCandidateStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresConversationAssuranceLedgerConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresConversationAssuranceLedgerConfig(
            dsn="postgresql://example",
            statement_timeout_ms=0,
        )


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled migration command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_assessment_and_dispute_survive_restart() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex
    config = PostgresConversationAssuranceLedgerConfig(dsn=dsn)
    store = PostgresConversationAssuranceLedger(config=config)
    assessment = AssessmentRecord(
        assessment_id=f"assessment-{suffix}",
        turn_id=f"turn-{suffix}",
        conversation_id=f"conversation-{suffix}",
        principal_scope=f"principal-{suffix}",
        question_digest="q" * 64,
        answer_digest="a" * 64,
        evidence_manifest_digest="e" * 64,
        rubric_version="1.0.0",
        model_set_digest="m" * 64,
        decision=AssuranceDecision(
            verdict=AssuranceVerdict.FAIL,
            content_score=25.0,
            confidence=1.0,
            reasons=("verification_failed",),
        ),
        assessed_at=_NOW,
    )
    dispute = DisputeRecord(
        dispute_id=f"dispute-{suffix}",
        assessment_id=assessment.assessment_id,
        principal_scope=assessment.principal_scope,
        reported_by=f"operator-{suffix}",
        reason=DisputeReason.WRONG_FACT,
        detail="The answer conflicts with the cited evidence.",
        evidence_refs=(),
        reported_at=_NOW,
    )

    assert await store.append_assessment(assessment)
    assert await store.append_dispute(dispute)
    restarted = PostgresConversationAssuranceLedger(config=config)

    assert (
        await restarted.get_assessment(
            principal_scope=assessment.principal_scope,
            assessment_id=assessment.assessment_id,
        )
        == assessment
    )
    assert await restarted.list_disputes(
        principal_scope=assessment.principal_scope,
        assessment_id=assessment.assessment_id,
    ) == (dispute,)
    assert (
        await restarted.get_dispute(
            principal_scope=assessment.principal_scope,
            dispute_id=dispute.dispute_id,
        )
        == dispute
    )
    assert (
        await restarted.get_dispute(
            principal_scope="other-principal",
            dispute_id=dispute.dispute_id,
        )
        is None
    )


@pytest.mark.integration
async def test_policy_candidate_transition_survives_restart() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex
    store = PostgresConversationPolicyCandidateStore(
        config=PostgresConversationPolicyCandidateStoreConfig(dsn=dsn)
    )
    candidate = ChatPolicyCandidate(
        candidate_id=f"candidate-{suffix}",
        principal_scope=f"principal-{suffix}",
        cluster_id=f"cluster-{suffix}",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest="p" * 64,
        incumbent_policy_digest="i" * 64,
    )
    transition = PolicyTransition(
        candidate_id=candidate.candidate_id,
        from_stage=PolicyStage.SHADOW,
        to_stage=PolicyStage.CANARY_1,
        reasons=("promotion_guards_passed",),
    )

    assert await store.append_candidate(candidate)
    updated = await store.apply_transition(
        principal_scope=candidate.principal_scope,
        transition=transition,
    )
    restarted = PostgresConversationPolicyCandidateStore(
        config=PostgresConversationPolicyCandidateStoreConfig(dsn=dsn)
    )

    assert updated.stage is PolicyStage.CANARY_1
    assert (
        await restarted.get_candidate(
            principal_scope=candidate.principal_scope,
            candidate_id=candidate.candidate_id,
        )
        == updated
    )
    assert await restarted.list_transitions(
        principal_scope=candidate.principal_scope,
        candidate_id=candidate.candidate_id,
    ) == (transition,)
