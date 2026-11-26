"""Operator projection ordering, expiry and authority remain read-only."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.observer_deployment_projection import (
    ObserverProposalReader,
    merge_projection,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverProposalProjection

from .test_runtime_projection_reader import RecordingFallback, _query

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def projection(*, offset=0, revision=1, target="cluster-example"):
    value = {
        "schema_version": "1.0.0",
        "target_ref": target,
        "source_revision": revision,
        "published_at": (NOW + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(seconds=offset + 60)).isoformat().replace("+00:00", "Z"),
        "proposal": None,
        "state": "unavailable",
        "reason": "evidence_unavailable",
        "execution_authority": False,
    }
    return ObserverProposalProjection.model_validate(
        {**value, "projection_digest": canonical_digest(value)}
    )


def test_duplicate_older_and_same_time_conflicting_snapshots() -> None:
    initial = merge_projection(None, projection())
    assert merge_projection(initial, projection()) == initial
    fresh = merge_projection(initial, projection(offset=1, revision=2))
    assert merge_projection(fresh, projection()) == fresh
    conflict = merge_projection(fresh, projection(offset=1, revision=3))
    assert conflict["conflicted"] is True
    assert merge_projection(conflict, projection(offset=2, revision=2)) == conflict
    assert merge_projection(conflict, projection(offset=1, revision=2))["conflicted"] is True
    with pytest.raises(ValueError, match="target"):
        merge_projection(fresh, projection(target="other"))


async def test_reader_uses_only_operator_projection_store() -> None:
    class Store:
        async def read(self, target_ref):
            return [merge_projection(None, projection())]

    fallback = RecordingFallback()
    reader = ObserverProposalReader(Store(), fallback=fallback, now=lambda: NOW)
    result = await reader.read(_query("observer.deployment.proposals"))
    assert result["items"][0]["state"] == "unavailable"
    assert result["items"][0]["proposal"] is None
    assert result["execution_authority"] is False
    assert fallback.operations == []
    await reader.read(_query("other"))
    assert fallback.operations == ["other"]


def current_projection():
    candidates = [
        {
            "method": method,
            "egress": egress,
            "profile": "observer.snapshot.mtls-pvc.v1",
            "state": "unknown",
            "blockers": [],
            "missing": ["kubernetes_read"],
        }
        for method in ("gitops", "existing_host", "managed_host", "run_command")
        for egress in ("private", "public")
    ]
    proposal = {
        "schema_version": "1.0.0",
        "target_ref": "cluster-example",
        "context_digest": "sha256:" + "a" * 64,
        "evaluated_at": "2026-09-19T00:00:00Z",
        "expires_at": "2026-09-19T00:05:00Z",
        "status": "needs_evidence",
        "candidates": candidates,
        "recommended": None,
        "approval_required": True,
        "execution_authority": False,
    }
    proposal["proposal_digest"] = canonical_digest(proposal)
    value = projection().model_dump(mode="json", exclude={"projection_digest"})
    value.update({"state": "current", "reason": "current_evidence", "proposal": proposal})
    return ObserverProposalProjection.model_validate(
        {**value, "projection_digest": canonical_digest(value)}
    )


async def test_current_content_is_withheld_after_expiry_and_conflict() -> None:
    record = merge_projection(None, current_projection())

    class Store:
        async def read(self, target_ref):
            return [record]

    clock = [NOW]
    reader = ObserverProposalReader(Store(), fallback=RecordingFallback(), now=lambda: clock[0])
    assert (await reader.read(_query("observer.deployment.proposals")))["items"][0][
        "proposal"
    ] is not None
    clock[0] += timedelta(minutes=1)
    assert (await reader.read(_query("observer.deployment.proposals")))["items"][0][
        "proposal"
    ] is None
    clock[0] = NOW
    record["conflicted"] = True
    result = await reader.read(_query("observer.deployment.proposals"))
    assert result["items"][0]["reason"] == "conflict"
    assert result["items"][0]["proposal"] is None


async def test_consumer_lifecycle_stores_before_advancing_and_quarantines_malformed() -> None:
    import asyncio

    from fdai_operator_service.observer_deployment_projection import ObserverProposalBridge
    from fdai_service_contracts.observer_deployment import (
        OBSERVER_PROPOSAL_GROUP,
        OBSERVER_PROPOSAL_TOPIC,
    )

    stored, published = [], []
    consumed = asyncio.Event()
    never = asyncio.Event()

    class Store:
        async def retain(self, value):
            stored.append(value)

    class Source:
        async def probe_readiness(self):
            return True

        async def subscribe(self, topic, group_id):
            assert (topic, group_id) == (OBSERVER_PROPOSAL_TOPIC, OBSERVER_PROPOSAL_GROUP)
            yield {"invalid": "not retained"}
            assert len(published) == 1
            yield projection(offset=1).model_dump(mode="json")
            assert len(published) == 2
            yield current_projection().model_dump(mode="json")
            assert len(stored) == 1
            consumed.set()
            await never.wait()

        async def publish(self, topic, key, payload):
            published.append((topic, payload))

    source = Source()
    bridge = ObserverProposalBridge(store=Store(), source=source, publisher=source, now=lambda: NOW)
    try:
        await bridge.start()
        await asyncio.wait_for(consumed.wait(), timeout=2)
        assert bridge.workers_ready()
        assert (
            published
            == [(OBSERVER_PROPOSAL_TOPIC + ".dlq", {"reason": "invalid_observer_projection"})] * 2
        )
    finally:
        await bridge.aclose()
    assert not bridge.workers_ready()


async def test_retry_log_excludes_provider_message_and_payload(monkeypatch, caplog) -> None:
    import asyncio

    import psycopg
    from fdai_operator_service import observer_deployment_projection as module

    suspended = asyncio.Event()
    never = asyncio.Event()

    async def suspend_retry(delay):
        suspended.set()
        await never.wait()

    class Source:
        async def probe_readiness(self):
            raise psycopg.errors.InsufficientPrivilege("sensitive provider payload")

    monkeypatch.setattr(module.asyncio, "sleep", suspend_retry)
    source = Source()
    bridge = module.ObserverProposalBridge(store=object(), source=source, publisher=object())
    try:
        await bridge.start()
        await asyncio.wait_for(suspended.wait(), timeout=2)
        assert not bridge.workers_ready()
        record = next(
            record
            for record in caplog.records
            if record.message == "observer_proposal_projection_retrying"
        )
        assert record.failure_type == "InsufficientPrivilege"
        assert record.sqlstate == "42501"
        assert "sensitive provider payload" not in caplog.text
        assert record.exc_info is None
    finally:
        await bridge.aclose()


@pytest.mark.parametrize("driver", ("postgresql", "postgresql+psycopg"))
@pytest.mark.parametrize("operation", ("read", "retain"))
async def test_store_normalizes_dsn_before_driver_connection(
    monkeypatch, driver, operation
) -> None:
    from unittest.mock import AsyncMock

    import psycopg
    from fdai_operator_service.observer_deployment_projection import PostgresObserverProjectionStore

    connect = AsyncMock(side_effect=RuntimeError("connection boundary reached"))
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresObserverProjectionStore(f"{driver}://user@example.com/database")

    with pytest.raises(RuntimeError, match="connection boundary reached"):
        if operation == "read":
            await store.read(None)
        else:
            await store.retain(projection())

    connect.assert_awaited_once()
    assert connect.call_args.args == ("postgresql://user@example.com/database",)


@pytest.mark.integration
async def test_postgres_observer_projection_atomic_ordering() -> None:
    import asyncio
    import os
    import uuid

    import psycopg
    from fdai_operator_service.observer_deployment_projection import PostgresObserverProjectionStore
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = os.environ.get("FDAI_CONNECTOR_TEST_DSN")
    if not dsn:
        pytest.skip("explicit loopback connector test DSN is unset")
    parsed = conninfo_to_dict(dsn)
    if (
        parsed.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or parsed.get("hostaddr") not in {None, "127.0.0.1", "::1"}
        or parsed.get("service")
    ):
        pytest.fail("observer projection verification requires loopback PostgreSQL")
    schema = "observer_projection_" + uuid.uuid4().hex
    connection = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=3)
    try:
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        await connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        await connection.execute(
            "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        store = PostgresObserverProjectionStore(
            make_conninfo(dsn, options=f"-c search_path={schema}")
        )
        await asyncio.gather(
            *(store.retain(projection(offset=index, revision=index + 1)) for index in range(8))
        )
        rows = await store.read("cluster-example")
        assert len(rows) == 1
        assert rows[0]["projection"]["source_revision"] == 8
        await store.retain(projection(offset=7, revision=9))
        assert (await store.read("cluster-example"))[0]["conflicted"] is True
        await store.retain(projection(offset=8, revision=10))
        assert (await store.read("cluster-example"))[0]["conflicted"] is False
        assert await store.read("other") == []
    finally:
        await connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        await connection.close()
