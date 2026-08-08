"""PostgreSQL atomic memory compaction promotion and rollback tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.operator_memory import (
    MemoryCategory,
    MemoryCompactionService,
    MemoryCompactionState,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)
from fdai.delivery.persistence import (
    PostgresMemoryCompactionRepository,
    PostgresMemoryCompactionRepositoryConfig,
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 17, 11, 0, tzinfo=UTC)


class _Authorizer:
    def can_review(self, actor_id: str) -> bool:
        return actor_id == "owner-example"


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


def _entry(uid: uuid.UUID, source_ref: str, *, scope_ref: str) -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=uid,
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref=scope_ref,
        category=MemoryCategory.RUNBOOK_HINT,
        body=source_ref,
        source_event=MemorySource.HIL_REJECT,
        source_ref=source_ref,
        author="operator-a",
        approved_by="operator-b",
        created_at=_NOW,
    )


@pytest.mark.integration
async def test_promotion_and_rollback_are_atomic_and_restart_safe() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    memory = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    scope_ref = f"resource-group:integration-{uuid.uuid4()}"
    sources = (
        _entry(uuid.uuid4(), "hil.reject:first", scope_ref=scope_ref),
        _entry(uuid.uuid4(), "hil.reject:second", scope_ref=scope_ref),
    )
    for source in sources:
        await memory.append(source)
    config = PostgresMemoryCompactionRepositoryConfig(dsn=dsn)
    repository = PostgresMemoryCompactionRepository(config=config)
    service = MemoryCompactionService(repository=repository, authorizer=_Authorizer())
    candidate = await service.propose(
        sources,
        body="Use the approved recovery runbook.",
        proposed_by_agent="Norns",
        at=_NOW,
    )
    await service.review(
        candidate.candidate_id,
        reviewer_id="owner-example",
        approve=True,
        reason="Grounding verified.",
        at=_NOW,
    )
    promoted = await service.promote(candidate.candidate_id, actor_id="owner-example", at=_NOW)
    active_after_promote = await memory.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref=scope_ref,
    )
    assert [entry.id for entry in active_after_promote] == [promoted.promoted_entry_id]

    restarted = MemoryCompactionService(
        repository=PostgresMemoryCompactionRepository(config=config),
        authorizer=_Authorizer(),
    )
    rolled_back = await restarted.rollback(candidate.candidate_id, actor_id="owner-example")
    active_after_rollback = await memory.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref=scope_ref,
    )
    assert rolled_back.state is MemoryCompactionState.ROLLED_BACK
    assert {entry.id for entry in active_after_rollback} == {entry.id for entry in sources}
