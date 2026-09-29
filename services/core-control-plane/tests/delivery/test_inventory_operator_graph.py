"""The local reconciliation loop keeps the Console inventory graph on the active snapshot."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import psycopg
import pytest
from fdai.delivery import inventory_operator_graph as graph
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync_cli import _main
from fdai.shared.providers.inventory_snapshot import InventoryObservationKind


class _Store:
    def __init__(self, stored: Mapping[str, Any] | None = None) -> None:
        self.stored = stored
        self.writes: list[tuple[str, Mapping[str, Any]]] = []

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        assert key == graph.OPERATOR_INVENTORY_GRAPH_KEY
        return self.stored

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        self.writes.append((key, value))
        self.stored = value


def _payload(snapshot_id: str = "snapshot-2", *, age_days: int = 0) -> dict[str, object]:
    return graph.operator_inventory_payload(
        snapshot_id=snapshot_id,
        snapshot_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        now=datetime(2026, 9, 1 + age_days, 12, 1, tzinfo=UTC),
        source="arg",
        observation_kind=InventoryObservationKind.OBSERVED,
        freshness_budget_seconds=86400,
        resource_rows=[],
        link_rows=[],
    )


async def _reconcile(
    monkeypatch: pytest.MonkeyPatch, store: _Store, payload: dict[str, object] | None
) -> bool:
    monkeypatch.setattr(graph, "read_operator_inventory_graph", AsyncMock(return_value=payload))
    return await graph.reconcile_operator_inventory_graph(
        dsn="postgresql://example",
        state_store=store,  # type: ignore[arg-type]
    )


async def test_a_missing_or_newer_graph_is_written_and_an_unchanged_one_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _Store()
    current = _Store(_payload())
    older = _Store(_payload("snapshot-1"))

    assert await _reconcile(monkeypatch, empty, _payload()) is True
    # Only the age differs, so the stored projection already states this snapshot.
    assert await _reconcile(monkeypatch, current, {**_payload(), "cache": {}}) is False
    assert await _reconcile(monkeypatch, older, _payload()) is True
    assert [key for key, _ in empty.writes] == [graph.OPERATOR_INVENTORY_GRAPH_KEY]
    assert current.writes == []
    assert older.stored is not None and older.stored["snapshot_id"] == "snapshot-2"


async def test_a_graph_that_aged_past_its_freshness_budget_is_relabeled_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_payload())

    assert await _reconcile(monkeypatch, store, _payload(age_days=2)) is True
    assert store.stored is not None and store.stored["freshness"] == "stale"


async def test_without_an_active_snapshot_the_stored_graph_is_left_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(_payload())

    assert await _reconcile(monkeypatch, store, None) is False
    assert store.writes == []
    with pytest.raises(RuntimeError, match="active inventory snapshot is unavailable"):
        await graph.write_operator_inventory_graph(
            dsn="postgresql://example",
            state_store=store,  # type: ignore[arg-type]
        )


async def test_the_local_loop_projection_runs_only_when_enabled_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failing = AsyncMock(side_effect=psycopg.OperationalError("connection refused"))
    monkeypatch.setattr(graph, "reconcile_operator_inventory_graph", failing)

    await graph.reconcile_local_operator_graph("postgresql://example", {})
    await graph.reconcile_local_operator_graph(
        "postgresql://example", {graph.OPERATOR_GRAPH_PROJECTION_ENV: "true"}
    )
    assert failing.await_count == 0

    with caplog.at_level(logging.WARNING, logger=graph.__name__):
        await graph.reconcile_local_operator_graph(
            "postgresql://example", {graph.OPERATOR_GRAPH_PROJECTION_ENV: "1"}
        )

    assert failing.await_count == 1
    assert [record.message for record in caplog.records] == [
        "inventory_operator_graph_projection_failed"
    ]


async def test_the_reconciliation_loop_refreshes_the_local_graph_after_every_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {"FDAI_INVENTORY_DSN": "postgresql://example", "AZURE_SUBSCRIPTION_ID": "sub-1"}
    )

    class StopLoopError(RuntimeError):
        pass

    reconcile = AsyncMock()
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._load_job_config", AsyncMock(return_value=config)
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._run_due_once", AsyncMock(return_value=config)
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.inventory_sync_cli_support.reconcile_local_operator_graph",
        reconcile,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.asyncio.sleep",
        AsyncMock(side_effect=[None, StopLoopError()]),
    )

    with pytest.raises(StopLoopError):
        await _main(["--loop"])

    assert [call.args for call in reconcile.await_args_list] == [
        ("postgresql://example",),
        ("postgresql://example",),
    ]
