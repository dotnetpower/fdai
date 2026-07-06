"""Tests for :mod:`aiopspilot.delivery.read_api.read_model`.

Uses the in-memory fake in isolation - no HTTP layer needed here. The
Protocol conformance is asserted so a future Postgres-backed adapter that
implements the same three methods drops in with the same test contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aiopspilot.delivery.read_api.read_model import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AuditItem,
    ConsoleReadModel,
    HilQueueItem,
    InMemoryConsoleReadModel,
    clamp_limit,
)


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "actor": "test",
        "action_kind": "control_loop.abstain",
        "mode": "shadow",
        "outcome": "abstained",
        "recorded_at": "2026-07-06T00:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestClampLimit:
    def test_none_returns_default(self) -> None:
        assert clamp_limit(None) == DEFAULT_LIMIT

    def test_zero_or_negative_returns_one(self) -> None:
        assert clamp_limit(0) == 1
        assert clamp_limit(-99) == 1

    def test_over_max_is_capped(self) -> None:
        assert clamp_limit(MAX_LIMIT + 100) == MAX_LIMIT

    def test_in_range_passes_through(self) -> None:
        assert clamp_limit(25) == 25


class TestInMemoryConsoleReadModelIsProtocol:
    def test_conforms_to_protocol(self) -> None:
        model = InMemoryConsoleReadModel()
        assert isinstance(model, ConsoleReadModel)


class TestRecordAuditEntry:
    def test_appends_with_incrementing_seq(self) -> None:
        model = InMemoryConsoleReadModel()
        first = model.record_audit_entry(_entry())
        second = model.record_audit_entry(_entry())
        assert first.seq == 1
        assert second.seq == 2

    def test_previous_hash_chains(self) -> None:
        model = InMemoryConsoleReadModel()
        first = model.record_audit_entry(_entry())
        second = model.record_audit_entry(_entry())
        assert first.previous_hash == "0" * 64
        assert second.previous_hash == first.entry_hash

    def test_rejects_unknown_mode(self) -> None:
        model = InMemoryConsoleReadModel()
        with pytest.raises(ValueError, match="mode"):
            model.record_audit_entry(_entry(), mode="bogus")

    def test_missing_recorded_at_falls_back_to_now(self) -> None:
        model = InMemoryConsoleReadModel()
        entry = {k: v for k, v in _entry().items() if k != "recorded_at"}
        item = model.record_audit_entry(entry)
        # Parses as ISO 8601 (no exception).
        datetime.fromisoformat(item.recorded_at)

    def test_correlation_id_preserved_when_present(self) -> None:
        model = InMemoryConsoleReadModel()
        item = model.record_audit_entry(_entry(correlation_id="corr-1"))
        assert item.correlation_id == "corr-1"

    def test_correlation_id_none_when_missing(self) -> None:
        model = InMemoryConsoleReadModel()
        item = model.record_audit_entry(_entry())
        assert item.correlation_id is None


class TestListAudit:
    async def test_empty_page(self) -> None:
        model = InMemoryConsoleReadModel()
        page = await model.list_audit()
        assert page.items == ()
        assert page.next_cursor is None

    async def test_returns_newest_first(self) -> None:
        model = InMemoryConsoleReadModel()
        for i in range(5):
            model.record_audit_entry(_entry(action_kind=f"kind-{i}"))
        page = await model.list_audit(limit=10)
        seqs = [item.seq for item in page.items]
        assert seqs == [5, 4, 3, 2, 1]

    async def test_pagination_via_cursor(self) -> None:
        model = InMemoryConsoleReadModel()
        for i in range(7):
            model.record_audit_entry(_entry(action_kind=f"kind-{i}"))
        first = await model.list_audit(limit=3)
        assert [item.seq for item in first.items] == [7, 6, 5]
        assert first.next_cursor == "5"

        second = await model.list_audit(limit=3, cursor=first.next_cursor)
        assert [item.seq for item in second.items] == [4, 3, 2]
        assert second.next_cursor == "2"

        third = await model.list_audit(limit=3, cursor=second.next_cursor)
        assert [item.seq for item in third.items] == [1]
        assert third.next_cursor is None

    async def test_invalid_cursor_raises_value_error(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_audit_entry(_entry())
        with pytest.raises(ValueError, match="cursor"):
            await model.list_audit(cursor="not-a-number")

    async def test_empty_cursor_treated_as_none(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_audit_entry(_entry())
        page = await model.list_audit(cursor="")
        assert len(page.items) == 1

    async def test_limit_is_clamped(self) -> None:
        model = InMemoryConsoleReadModel()
        for _ in range(3):
            model.record_audit_entry(_entry())
        page = await model.list_audit(limit=MAX_LIMIT + 1000)
        assert len(page.items) == 3


class TestDashboardMetrics:
    async def test_empty_snapshot(self) -> None:
        model = InMemoryConsoleReadModel()
        kpi = await model.dashboard_metrics()
        assert kpi.event_count == 0
        assert kpi.shadow_share == 0.0
        assert kpi.enforce_share == 0.0
        assert kpi.hil_pending == 0
        assert kpi.last_recorded_at is None

    async def test_shadow_and_enforce_shares(self) -> None:
        model = InMemoryConsoleReadModel()
        for _ in range(3):
            model.record_audit_entry(_entry(mode="shadow"))
        for _ in range(1):
            model.record_audit_entry(_entry(mode="enforce"))
        kpi = await model.dashboard_metrics()
        assert kpi.event_count == 4
        assert kpi.shadow_share == 0.75
        assert kpi.enforce_share == 0.25

    async def test_group_counts(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_audit_entry(_entry(action_kind="a", outcome="ok"))
        model.record_audit_entry(_entry(action_kind="a", outcome="ok"))
        model.record_audit_entry(_entry(action_kind="b", outcome="failed"))
        kpi = await model.dashboard_metrics()
        assert kpi.by_action_kind == {"a": 2, "b": 1}
        assert kpi.by_outcome == {"ok": 2, "failed": 1}

    async def test_hil_pending_counted(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k",
                event_id="e",
                action_kind="ak",
                reason="r",
                requested_at=datetime.now(tz=UTC).isoformat(),
            )
        )
        kpi = await model.dashboard_metrics()
        assert kpi.hil_pending == 1

    async def test_last_recorded_at_is_latest(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_audit_entry(_entry(recorded_at="2026-07-06T01:00:00+00:00"))
        model.record_audit_entry(_entry(recorded_at="2026-07-06T02:00:00+00:00"))
        kpi = await model.dashboard_metrics()
        assert kpi.last_recorded_at == "2026-07-06T02:00:00+00:00"


class TestHilQueue:
    async def test_empty(self) -> None:
        model = InMemoryConsoleReadModel()
        page = await model.list_hil_queue()
        assert page.items == ()

    async def test_newest_first_and_limit(self) -> None:
        model = InMemoryConsoleReadModel()
        for i in range(5):
            model.record_hil_pending(
                HilQueueItem(
                    idempotency_key=f"k-{i}",
                    event_id=f"e-{i}",
                    action_kind="ak",
                    reason="r",
                    requested_at=datetime.now(tz=UTC).isoformat(),
                )
            )
        page = await model.list_hil_queue(limit=3)
        keys = [item.idempotency_key for item in page.items]
        assert keys == ["k-4", "k-3", "k-2"]


class TestAuditItemSerialization:
    def test_to_dict_includes_all_fields(self) -> None:
        item = AuditItem(
            seq=1,
            event_id="e",
            correlation_id="c",
            actor="a",
            action_kind="k",
            mode="shadow",
            entry={"foo": "bar"},
            entry_hash="hash",
            previous_hash="prev",
            recorded_at="2026-07-06T00:00:00+00:00",
        )
        payload = item.to_dict()
        assert payload["seq"] == 1
        assert payload["entry"] == {"foo": "bar"}
        # No callable / non-serializable back-channels.
        assert set(payload) == {
            "seq",
            "event_id",
            "correlation_id",
            "actor",
            "action_kind",
            "mode",
            "entry",
            "entry_hash",
            "previous_hash",
            "recorded_at",
        }


class TestClearAndObservability:
    def test_clear_wipes_everything(self) -> None:
        model = InMemoryConsoleReadModel()
        model.record_audit_entry(_entry())
        model.record_hil_pending(
            HilQueueItem(
                idempotency_key="k",
                event_id="e",
                action_kind="ak",
                reason="r",
                requested_at=datetime.now(tz=UTC).isoformat(),
            )
        )
        model.clear()
        assert list(model.audit_items) == []

    def test_audit_items_view_is_read_only(self) -> None:
        model = InMemoryConsoleReadModel()
        item = model.record_audit_entry(_entry())
        view = tuple(model.audit_items)
        assert view == (item,)
