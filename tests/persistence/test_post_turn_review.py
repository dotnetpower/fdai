"""Integration tests for durable post-turn review persistence."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.learning import PostTurnReviewState
from fdai.core.learning.ledger import pending_record
from fdai.core.learning.models import EligibilityReason
from fdai.core.operator_memory import (
    MemoryCategory,
    OperatorMemoryProposal,
    OperatorMemoryProposalState,
    ScopeKind,
)
from fdai.delivery.persistence import (
    PostgresOperatorMemoryProposalStore,
    PostgresOperatorMemoryProposalStoreConfig,
    PostgresPostTurnReviewLedger,
    PostgresPostTurnReviewLedgerConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 20, 5, tzinfo=UTC)


def test_configs_reject_empty_dsn_and_bad_timeouts() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresPostTurnReviewLedgerConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresPostTurnReviewLedgerConfig(dsn="postgresql://x", connect_timeout_s=0)
    with pytest.raises(ValueError, match="dsn"):
        PostgresOperatorMemoryProposalStoreConfig(dsn="")


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_proposal_claim_is_atomic_across_ledger_instances() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex
    config = PostgresPostTurnReviewLedgerConfig(dsn=dsn)
    first = PostgresPostTurnReviewLedger(config=config)
    second = PostgresPostTurnReviewLedger(config=config)
    for ledger, review_id in ((first, f"review-{suffix}-1"), (second, f"review-{suffix}-2")):
        await ledger.start(
            pending_record(
                review_id=review_id,
                principal_scope=f"principal-{suffix}",
                reasons=(EligibilityReason.ELIGIBLE_CORRECTION,),
                at=_NOW,
            )
        )

    results = await asyncio.gather(
        first.reserve_proposal(
            review_id=f"review-{suffix}-1",
            dedup_key=f"post-turn-proposal:{suffix}",
        ),
        second.reserve_proposal(
            review_id=f"review-{suffix}-2",
            dedup_key=f"post-turn-proposal:{suffix}",
        ),
    )

    assert sorted(results) == [False, True]


@pytest.mark.integration
async def test_review_terminal_state_survives_restart() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex
    config = PostgresPostTurnReviewLedgerConfig(dsn=dsn)
    store = PostgresPostTurnReviewLedger(config=config)
    review_id = f"review-{suffix}"
    await store.start(
        pending_record(
            review_id=review_id,
            principal_scope=f"principal-{suffix}",
            reasons=(EligibilityReason.ELIGIBLE_CORRECTION,),
            at=_NOW,
        )
    )
    await store.finish(
        review_id,
        state=PostTurnReviewState.ABSTAINED,
        reasons=("insufficient_evidence",),
        updated_at=_NOW,
    )

    restarted = PostgresPostTurnReviewLedger(config=config)

    assert (await restarted.get(review_id)).state is PostTurnReviewState.ABSTAINED


@pytest.mark.integration
async def test_operator_memory_proposal_survives_restart_and_transition_is_cas() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex
    body = "Use the scoped evidence query before escalation."
    proposal = OperatorMemoryProposal(
        proposal_id=f"operator-memory-proposal:{suffix}",
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        scope_kind=ScopeKind.RESOURCE,
        scope_ref=f"resource-{suffix}",
        category=MemoryCategory.RUNBOOK_HINT,
        body=body,
        evidence_refs=(f"audit:{suffix}",),
        proposed_by_agent="Norns",
        created_at=_NOW,
    )
    config = PostgresOperatorMemoryProposalStoreConfig(dsn=dsn)
    store = PostgresOperatorMemoryProposalStore(config=config)
    await store.create(proposal)
    approved = replace(
        proposal,
        state=OperatorMemoryProposalState.APPROVED,
        reviewed_by="reviewer-example",
        review_reason="Evidence supports this bounded note.",
        reviewed_at=_NOW,
    )

    assert (
        await store.transition(approved, expected_state=OperatorMemoryProposalState.DRAFT)
        == approved
    )
    assert (
        await store.transition(approved, expected_state=OperatorMemoryProposalState.DRAFT) is None
    )

    restarted = PostgresOperatorMemoryProposalStore(config=config)
    assert (await restarted.get(proposal.proposal_id)).state is OperatorMemoryProposalState.APPROVED
