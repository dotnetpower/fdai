"""Active Inventory projection and bounded replay without provider calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.assurance_twin_inventory import (
    PostgresTwinInventorySource,
    TwinInventoryUnavailableError,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.projection import ResourceRef

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
BASE = ResourceRef("Resource", "resource-a")


class Cursor:
    def __init__(
        self, *, one: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None
    ):
        self.one = one
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.one

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class Connection:
    def __init__(
        self,
        *,
        snapshot: dict[str, Any] | None,
        resources: list[dict[str, Any]],
        deltas: list[dict[str, Any]],
        links: bool = False,
        active_id: str | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.resources = resources
        self.deltas = deltas
        self.links = links
        self.active_id = active_id
        self.sql: list[str] = []

    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    def transaction(self) -> Connection:
        return self

    async def execute(self, query: str, params: object = None) -> Cursor:
        self.sql.append(query)
        if "FROM inventory_active a JOIN inventory_snapshot" in query:
            return Cursor(one=self.snapshot)
        if "FROM inventory_snapshot_resource" in query:
            return Cursor(rows=self.resources)
        if "FROM inventory_realtime_resource ORDER" in query:
            return Cursor(rows=self.deltas)
        if "FROM inventory_realtime_link" in query:
            return Cursor(one={"pending_links": self.links})
        if "SELECT snapshot_id FROM inventory_active" in query:
            return Cursor(
                one={"snapshot_id": self.active_id or self.snapshot["id"]}
                if self.snapshot is not None
                else None
            )
        return Cursor()


def _snapshot(**changes: Any) -> dict[str, Any]:
    return {
        "id": "generation-one",
        "source": "retained-inventory",
        "status": "active",
        "observation_kind": "observed",
        "scopes": ["scope-a"],
        "metadata": {"coverage_scope": "full_provider_scope"},
        "started_at": NOW - timedelta(minutes=5),
        "completed_at": NOW - timedelta(minutes=4),
        "newer_failure": False,
        **changes,
    }


def _resource(name: str = "resource-a", **props: Any) -> dict[str, Any]:
    return {"resource_id": name, "resource_type": "Resource", "props": props or {"old": True}}


def _delta(name: str, kind: str, **props: Any) -> dict[str, Any]:
    return {
        "resource_id": name,
        "resource_type": "Resource",
        "props": props,
        "change_kind": kind,
        "observed_at": NOW - timedelta(minutes=1),
    }


def _source(
    monkeypatch: pytest.MonkeyPatch, connection: Connection, **limits: int
) -> PostgresTwinInventorySource:
    async def connect(*_args: object, **_kwargs: object) -> Connection:
        return connection

    monkeypatch.setattr(
        "fdai.delivery.assurance_twin_inventory.psycopg.AsyncConnection.connect", connect
    )
    return PostgresTwinInventorySource(
        config=PostgresInventorySnapshotStoreConfig(dsn="unused"),
        **limits,
    )


async def _load(source: PostgresTwinInventorySource) -> Any:
    return await source.load(
        now=NOW, freshness_ttl=timedelta(minutes=10), required_scopes=("scope-a",)
    )


@pytest.mark.asyncio
async def test_active_generation_replays_resource_overlay_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(
        snapshot=_snapshot(),
        resources=[_resource(), _resource("resource-b")],
        deltas=[
            _delta("resource-a", "upsert", replacement=True),
            _delta("resource-b", "delete"),
            _delta("resource-c", "upsert", created=True),
        ],
    )
    source = _source(monkeypatch, connection)

    first = await _load(source)
    second = await _load(_source(monkeypatch, connection))

    assert first == second
    assert first.snapshot_id == "generation-one"
    assert first.source_revision.startswith("sha256:")
    assert len(first.source_revision) == 71
    assert first.resource_count == 2 and first.delta_count == 3
    assert first.projection.properties(BASE) == {"replacement": True}
    assert not first.projection.contains(ResourceRef("Resource", "resource-b"))
    assert first.projection.properties(ResourceRef("Resource", "resource-c")) == {"created": True}
    assert connection.sql[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "pg_advisory_xact_lock_shared" in connection.sql[2]
    assert connection.sql.count(connection.sql[0]) == 2


@pytest.mark.asyncio
async def test_revision_fences_snapshot_and_realtime_content_not_just_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(
        snapshot=_snapshot(),
        resources=[_resource()],
        deltas=[_delta("resource-a", "upsert", replacement=True)],
    )
    source = _source(monkeypatch, connection)
    initial = await _load(source)
    assert (
        await source.load_at_revision(
            expected_revision=initial.source_revision,
            now=NOW,
            freshness_ttl=timedelta(minutes=10),
            required_scopes=("scope-a",),
        )
    ) == initial
    connection.resources = [_resource(old=False)]
    baseline_changed = await _load(source)
    assert initial.snapshot_id == baseline_changed.snapshot_id
    assert initial.source_revision != baseline_changed.source_revision
    with pytest.raises(TwinInventoryUnavailableError, match="revision changed"):
        await source.load_at_revision(
            expected_revision=initial.source_revision,
            now=NOW,
            freshness_ttl=timedelta(minutes=10),
            required_scopes=("scope-a",),
        )
    connection.resources = [_resource()]
    connection.deltas = [_delta("resource-a", "upsert", replacement=False)]
    overlay_changed = await _load(source)
    assert initial.source_revision != overlay_changed.source_revision
    connection.deltas = [_delta("resource-a", "upsert", replacement=True)]
    connection.deltas[0]["observed_at"] -= timedelta(seconds=1)
    time_changed = await _load(source)
    assert initial.source_revision != time_changed.source_revision
    connection.deltas[0]["observed_at"] += timedelta(seconds=1)
    replay = await _load(_source(monkeypatch, connection))
    assert replay.source_revision == initial.source_revision
    connection.snapshot = _snapshot(id="generation-two")
    assert (await _load(source)).source_revision != initial.source_revision


@pytest.mark.asyncio
async def test_revision_is_canonical_for_property_order_and_rejects_unhashable_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(
        snapshot=_snapshot(),
        resources=[_resource(a=1, b=2)],
        deltas=[_delta("resource-b", "upsert", x=1, y=2)],
    )
    source = _source(monkeypatch, connection)
    first = await _load(source)
    connection.resources = [_resource(b=2, a=1)]
    connection.deltas = [_delta("resource-b", "upsert", y=2, x=1)]
    assert (await _load(source)).source_revision == first.source_revision
    connection.resources = [_resource(invalid=float("nan"))]
    with pytest.raises(TwinInventoryUnavailableError, match="revision material"):
        await _load(source)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"status": "collecting"},
        {"observation_kind": "expected"},
        {"newer_failure": True},
        {"completed_at": NOW - timedelta(hours=1)},
        {"completed_at": NOW + timedelta(seconds=1)},
        {"scopes": ["other-scope"]},
        {"scopes": ["scope-a", "other-scope"]},
        {"metadata": {"coverage_scope": "requested_resource_types"}},
        {"metadata": "{invalid"},
    ],
)
async def test_untrustworthy_generation_fails_before_reading_bodies(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    connection = Connection(snapshot=_snapshot(**changes), resources=[_resource()], deltas=[])
    with pytest.raises(TwinInventoryUnavailableError):
        await _load(_source(monkeypatch, connection))
    assert not any("FROM inventory_snapshot_resource" in sql for sql in connection.sql)


@pytest.mark.asyncio
async def test_missing_generation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TwinInventoryUnavailableError):
        await _load(_source(monkeypatch, Connection(snapshot=None, resources=[], deltas=[])))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resources", "deltas", "links", "max_resources", "max_deltas"),
    [
        ([_resource(), _resource("resource-b")], [], False, 1, 3),
        ([_resource()], [_delta("a", "delete"), _delta("b", "delete")], False, 2, 1),
        ([_resource()], [], True, 2, 2),
        ([_resource()], [_delta("resource-b", "upsert", new=True)], False, 1, 2),
        ([_resource()], [_delta("resource-a", "unknown")], False, 2, 2),
        (
            [_resource()],
            [{**_delta("resource-a", "upsert"), "observed_at": NOW - timedelta(hours=1)}],
            False,
            2,
            2,
        ),
    ],
)
async def test_bounded_or_inconsistent_overlay_never_returns_a_projection(
    monkeypatch: pytest.MonkeyPatch,
    resources: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    links: bool,
    max_resources: int,
    max_deltas: int,
) -> None:
    connection = Connection(snapshot=_snapshot(), resources=resources, deltas=deltas, links=links)
    with pytest.raises(TwinInventoryUnavailableError):
        await _load(
            _source(
                monkeypatch,
                connection,
                max_resources=max_resources,
                max_deltas=max_deltas,
            )
        )


@pytest.mark.asyncio
async def test_new_generation_is_read_again_instead_of_reusing_an_old_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(snapshot=_snapshot(), resources=[_resource()], deltas=[])
    source = _source(monkeypatch, connection)
    first = await _load(source)
    connection.snapshot = _snapshot(id="generation-two")
    connection.resources = [_resource("resource-b")]
    second = await _load(source)

    assert first.snapshot_id != second.snapshot_id
    assert first.projection.contains(BASE)
    assert not second.projection.contains(BASE)


@pytest.mark.asyncio
async def test_promotion_during_lock_wait_fails_second_generation_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(
        snapshot=_snapshot(),
        resources=[_resource()],
        deltas=[],
        active_id="generation-two",
    )
    with pytest.raises(TwinInventoryUnavailableError, match="generation changed"):
        await _load(_source(monkeypatch, connection))


@pytest.mark.asyncio
async def test_invalid_cutoff_scope_and_limits_fail_without_database_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(snapshot=_snapshot(), resources=[], deltas=[])
    source = _source(monkeypatch, connection)
    with pytest.raises(ValueError):
        await source.load(
            now=NOW.replace(tzinfo=None),
            freshness_ttl=timedelta(minutes=1),
            required_scopes=("scope-a",),
        )
    with pytest.raises(ValueError):
        await source.load(now=NOW, freshness_ttl=timedelta(0), required_scopes=("scope-a",))
    with pytest.raises(ValueError):
        await source.load(now=NOW, freshness_ttl=timedelta(minutes=1), required_scopes=("b", "a"))
    with pytest.raises(ValueError):
        PostgresTwinInventorySource(
            config=PostgresInventorySnapshotStoreConfig(dsn="unused"), max_deltas=0
        )
    assert connection.sql == []
