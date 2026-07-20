from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fdai.delivery.persistence.postgres_scheduled_continuation import (
    PostgresScheduledContinuationStoreConfig,
    PostgresScheduledConversationAnchorStore,
    _row_to_anchor,
    _values,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAnchorState,
    ContinuationMode,
    ScheduledConversationAnchor,
    ScheduledResultOrigin,
    anchor_id_for_run,
)

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


def _anchor(*, suffix: str = "") -> ScheduledConversationAnchor:
    run_id = f"run-{suffix or '1'}"
    return ScheduledConversationAnchor(
        anchor_id=anchor_id_for_run(task_id="task-1", run_id=run_id),
        task_id="task-1",
        run_id=run_id,
        owner_principal_id="principal-a",
        scope_ref="scope-a",
        mode=ContinuationMode.ORIGIN_THREAD,
        origin=ScheduledResultOrigin(
            channel_kind="web",
            channel_ref="console",
            conversation_ref="conversation-1",
        ),
        result_digest="a" * 64,
        result_summary="Scheduled result",
        evidence_refs=("audit:1",),
        observation_started_at=NOW - timedelta(hours=1),
        observation_ended_at=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def test_anchor_row_codec_round_trips() -> None:
    anchor = _anchor()
    columns = (
        "anchor_id task_id run_id owner_principal_id scope_ref mode origin result_digest "
        "result_summary evidence_refs observation_started_at observation_ended_at created_at "
        "expires_at state"
    ).split()
    row = dict(zip(columns, _values(anchor), strict=True))

    assert _row_to_anchor(row) == anchor


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_postgres_anchor_store_is_idempotent_and_expires_with_cas() -> None:
    store = PostgresScheduledConversationAnchorStore(
        config=PostgresScheduledContinuationStoreConfig(dsn=os.environ["FDAI_DATABASE_URL"])
    )
    anchor = _anchor(suffix=uuid4().hex[:8])

    assert await store.create(anchor) == anchor
    assert await store.create(anchor) == anchor
    expired = await store.expire(
        anchor_id=anchor.anchor_id,
        expected_state=ContinuationAnchorState.ACTIVE,
    )
    assert expired is not None and expired.state is ContinuationAnchorState.EXPIRED
