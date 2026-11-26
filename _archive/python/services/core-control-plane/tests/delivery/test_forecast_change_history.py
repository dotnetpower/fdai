from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)
from fdai.delivery.forecast_change_history import ForecastChangeHistoryWitness
from fdai.delivery.persistence.postgres_forecast_change_history import (
    ForecastChangeHistoryCursor,
    ForecastChangeHistoryPage,
    ForecastChangeHistoryQuery,
)

NOW = datetime(2026, 9, 20, tzinfo=UTC)
QUERY = ForecastChangeHistoryQuery(
    "scope-example",
    "resource-example",
    NOW - timedelta(hours=1),
    NOW,
    NOW,
    page_size=2,
)


def row(
    watermark: int,
    *,
    source: str = ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    event: str | None = None,
    revision: str = "revision-1",
    status: str | None = None,
) -> dict[str, Any]:
    digest = "sha256:" + f"{watermark:064x}"
    return {
        "watermark": watermark,
        "observation_id": digest,
        "content_digest": digest,
        "idempotency_key": f"key-{watermark}",
        "subject_kind": "object",
        "scope_ref": QUERY.scope_ref,
        "subject_ref": QUERY.subject_ref,
        "subject_type": "compute.vm",
        "observation_kind": "full"
        if source == ARG_RESOURCE_CHANGE_SOURCE_IDENTITY
        else "change_hint",
        "mutation_kind": "upsert",
        "operation": None if source == ARG_RESOURCE_CHANGE_SOURCE_IDENTITY else "write",
        "operation_status": status,
        "source_identity": source,
        "source_event_id": event or f"event-{watermark}",
        "source_revision": revision,
        "effective_at": NOW - timedelta(minutes=watermark),
        "recorded_at": NOW - timedelta(seconds=watermark),
    }


class MemoryReader:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls = 0

    async def read_page(
        self,
        query: ForecastChangeHistoryQuery,
        *,
        cursor: ForecastChangeHistoryCursor | None = None,
    ) -> ForecastChangeHistoryPage:
        self.calls += 1
        fence = max((item["watermark"] for item in self.rows), default=0)
        if cursor is not None:
            fence = cursor.fence_watermark
        ordered = sorted(
            (item for item in self.rows if item["watermark"] <= fence),
            key=lambda item: (item["effective_at"], item["recorded_at"], item["watermark"]),
        )
        if cursor is not None:
            after = (cursor.effective_at, cursor.recorded_at, cursor.watermark)
            ordered = [
                item
                for item in ordered
                if (item["effective_at"], item["recorded_at"], item["watermark"]) > after
            ]
        page = ordered[: query.page_size]
        next_cursor = None
        if len(ordered) > query.page_size:
            last = page[-1]
            next_cursor = ForecastChangeHistoryCursor(
                query.identity,
                fence,
                last["effective_at"],
                last["recorded_at"],
                last["watermark"],
            )
        return ForecastChangeHistoryPage(tuple(page), next_cursor, fence)


async def test_witness_retains_all_observations_and_corrections_without_scoring() -> None:
    original = row(3, event="event-a")
    correction = row(2, event="event-a", revision="revision-2")
    # A correction can revise the effective time while its later recorded time governs lineage.
    correction["effective_at"] = NOW - timedelta(minutes=50)
    correction["recorded_at"] = NOW
    separate = row(
        1,
        source=ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
        status="Succeeded",
    )
    result = await ForecastChangeHistoryWitness(
        reader=MemoryReader([original, correction, separate])
    ).read(QUERY)
    assert result.exhausted
    assert len(result.changes) == 3
    assert result.coverage.complete is False
    assert result.coverage.limitation == "start_checkpoint_unverified"
    assert result.scoring_eligible is False and result.execution_authority is False
    original_witness = next(
        item
        for item in result.changes
        if item.source_revision == "revision-1" and item.source_event_id == "event-a"
    )
    revised_witness = next(item for item in result.changes if item.source_revision == "revision-2")
    assert original_witness.correction_of is None
    assert revised_witness.correction_of == original_witness.observation_ref
    assert revised_witness.effective_at == correction["effective_at"]
    assert revised_witness.recorded_at == correction["recorded_at"]
    assert all(
        item.synthetic is False and item.execution_authority is False for item in result.changes
    )


async def test_pending_duplicate_and_conflicting_revisions_fail_closed() -> None:
    pending = row(
        1, source=ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY, status="Started", event="pending"
    )
    conflicting = [row(2, event="conflict"), row(3, event="conflict")]
    same = row(4, event="duplicate")
    replay = dict(same, watermark=5)
    result = await ForecastChangeHistoryWitness(
        reader=MemoryReader([pending, *conflicting, same, replay])
    ).read(QUERY)
    assert len(result.changes) == 1
    assert result.changes[0].source_event_id == "duplicate"
    assert result.coverage.limitation == "conflicting_event"
    assert result.pending_event_ids == (f"{ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY}:pending",)
    assert result.duplicate_event_ids == (f"{ARG_RESOURCE_CHANGE_SOURCE_IDENTITY}:duplicate",)
    assert result.conflicting_event_ids == (f"{ARG_RESOURCE_CHANGE_SOURCE_IDENTITY}:conflict",)
    assert result.scoring_eligible is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope_ref", "other-scope"),
        ("subject_ref", "other-subject"),
        ("recorded_at", NOW + timedelta(seconds=1)),
        ("effective_at", NOW - timedelta(days=2)),
        ("source_identity", "inventory.reconciliation"),
        ("content_digest", "sha256:" + "f" * 64),
        ("observation_kind", "partial"),
        ("watermark", True),
        ("subject_kind", "relationship"),
    ],
)
async def test_untrusted_rows_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="forecast change history"):
        await ForecastChangeHistoryWitness(
            reader=MemoryReader([dict(row(1), **{field: value})])
        ).read(QUERY)


async def test_empty_and_truncated_reads_never_prove_no_changes() -> None:
    empty = await ForecastChangeHistoryWitness(reader=MemoryReader([])).read(QUERY)
    assert empty.changes == ()
    assert empty.exhausted
    assert empty.coverage.complete is False
    assert empty.coverage.fence_watermark == 0
    many = MemoryReader([row(index) for index in range(1, 259)])
    limited = await ForecastChangeHistoryWitness(reader=many).read(
        replace(QUERY, start_at=NOW - timedelta(hours=5), page_size=7)
    )
    assert len(limited.changes) == 256
    assert not limited.exhausted
    assert limited.coverage.limitation == "result_limit"
    assert many.calls == 37


async def test_restart_replays_exact_witness_without_upgrading_coverage() -> None:
    retained = [row(3), row(2), row(1)]
    first = await ForecastChangeHistoryWitness(reader=MemoryReader(retained)).read(QUERY)
    restarted = await ForecastChangeHistoryWitness(reader=MemoryReader(retained)).read(QUERY)
    assert restarted == first
    assert first.coverage.complete is False
    assert first.coverage.fence_watermark == 3


async def test_inconsistent_continuation_cannot_skip_a_journal_row() -> None:
    class BrokenReader(MemoryReader):
        async def read_page(
            self,
            query: ForecastChangeHistoryQuery,
            *,
            cursor: ForecastChangeHistoryCursor | None = None,
        ) -> ForecastChangeHistoryPage:
            page = await super().read_page(query, cursor=cursor)
            if page.next_cursor is not None:
                return replace(
                    page,
                    next_cursor=replace(page.next_cursor, watermark=page.next_cursor.watermark + 1),
                )
            return page

    with pytest.raises(ValueError, match="continuation"):
        await ForecastChangeHistoryWitness(reader=BrokenReader([row(3), row(2), row(1)])).read(
            QUERY
        )
