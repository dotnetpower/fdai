"""Integration tests for atomic PostgreSQL incident proposal consume."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.incident.intent import IncidentCreationProposal
from fdai.delivery.persistence import (
    PostgresIncidentProposalStore,
    PostgresStateStoreConfig,
)
from fdai.shared.contracts.models import IncidentSeverity

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_concurrent_take_returns_proposal_once() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    store = PostgresIncidentProposalStore(config=PostgresStateStoreConfig(dsn=dsn))
    operator_id = f"integration-{uuid.uuid4()}"
    session_id = f"session-{uuid.uuid4()}"
    now = datetime.now(tz=UTC)
    proposal = IncidentCreationProposal(
        requested_by=operator_id,
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        source_text="Open a SEV2 incident for target example-1",
        requested_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    await store.save(operator_id=operator_id, session_id=session_id, proposal=proposal)

    results = await asyncio.gather(
        *(store.take(operator_id=operator_id, session_id=session_id, now=now) for _ in range(8))
    )

    assert [result.status for result in results].count("found") == 1
    assert [result.status for result in results].count("missing") == 7
