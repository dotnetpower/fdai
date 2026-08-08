"""PostgreSQL runtime skill proposal persistence tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.skills import SkillProposal, SkillProposalState
from fdai.delivery.persistence import (
    PostgresSkillProposalStore,
    PostgresSkillProposalStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresSkillProposalStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresSkillProposalStoreConfig(dsn="postgresql://x", connect_timeout_s=0)


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
async def test_proposal_survives_restart_and_state_transition_is_cas() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    markdown = b"---\nname: example\n---\nbody\n"
    proposal = SkillProposal(
        proposal_id=f"skill-proposal:{suffix}",
        skill_name=f"example-{suffix}",
        content_hash=hashlib.sha256(markdown).hexdigest(),
        markdown=markdown,
        proposed_by_agent="Bragi",
        created_at=_NOW,
    )
    config = PostgresSkillProposalStoreConfig(dsn=dsn)
    store = PostgresSkillProposalStore(config=config)
    await store.create(proposal)
    reviewed = replace(
        proposal,
        state=SkillProposalState.APPROVED,
        reviewed_by="owner-example",
        review_reason="Verified.",
        reviewed_at=_NOW,
    )
    assert (
        await store.transition(
            reviewed,
            expected_state=SkillProposalState.DRAFT,
        )
        == reviewed
    )
    assert (
        await store.transition(
            reviewed,
            expected_state=SkillProposalState.DRAFT,
        )
        is None
    )

    restarted = PostgresSkillProposalStore(config=config)
    assert (await restarted.get(proposal.proposal_id)).state is SkillProposalState.APPROVED
