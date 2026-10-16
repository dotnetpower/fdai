"""W5 loopback PostgreSQL checks; telemetry and topology are labeled static fixtures."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
    graph_at,
)
from fdai.core.rca.telemetry_evidence import (
    TelemetryEvidenceDisposition,
    TelemetryEvidenceNeed,
    TelemetryEvidenceReceipt,
    build_telemetry_evidence_receipt,
)
from fdai.core.rca.telemetry_recipes import DEFAULT_TELEMETRY_RECIPE_CATALOG
from fdai.core.read_investigation.adaptive_contract import AdaptiveInvestigationDisposition
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
    ResourceLockOwnershipUnknownError,
    ResourceLockReleaseUnknownError,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
)
from fdai.runtime.adaptive_telemetry import (
    ConfiguredAdaptiveTelemetryInvestigator,
    build_adaptive_telemetry_investigator,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.process_runtime import ProcessEventKind, ProcessStatus
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20)]
_RELEASE = "sha256:" + "a" * 64
_RECEIPT = "sha256:" + "b" * 64

# Minimal adapter schema, not a migration/role test. No public-schema fallback is allowed.
_SCHEMA_SQL = """
CREATE TABLE process_runtime (
    process_id TEXT PRIMARY KEY, workflow_ref TEXT NOT NULL, workflow_version TEXT NOT NULL,
    status TEXT NOT NULL, current_step TEXT NOT NULL, target_resource_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
    correlation_id TEXT NOT NULL, revision BIGINT NOT NULL CHECK (revision >= 1)
);
CREATE TABLE process_event (
    seq BIGSERIAL PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
    process_id TEXT NOT NULL REFERENCES process_runtime(process_id), kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, recorded_at TIMESTAMPTZ NOT NULL,
    correlation_id TEXT NOT NULL, causation_id TEXT, step_id TEXT,
    attempt INTEGER NOT NULL CHECK (attempt >= 1), payload JSONB NOT NULL
);
CREATE TABLE process_projection_outbox (
    event_id TEXT PRIMARY KEY REFERENCES process_event(event_id),
    process_id TEXT NOT NULL REFERENCES process_runtime(process_id),
    available_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE topology_revision_batch (
    revision_id TEXT PRIMARY KEY, provider_generation_ref TEXT NOT NULL,
    ontology_release_digest TEXT NOT NULL, source_receipt_digest TEXT NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL,
    complete_snapshot BOOLEAN NOT NULL
);
CREATE TABLE topology_object_revision (
    revision_id TEXT NOT NULL REFERENCES topology_revision_batch(revision_id),
    object_id TEXT NOT NULL, object_type TEXT NOT NULL, properties JSONB NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL,
    deleted BOOLEAN NOT NULL, evidence_ref TEXT NOT NULL,
    PRIMARY KEY (revision_id, object_id)
);
CREATE TABLE topology_link_revision (
    revision_id TEXT NOT NULL REFERENCES topology_revision_batch(revision_id),
    from_id TEXT NOT NULL, from_type TEXT NOT NULL, link_type TEXT NOT NULL,
    to_id TEXT NOT NULL, to_type TEXT NOT NULL, properties JSONB NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL, recorded_at TIMESTAMPTZ NOT NULL,
    deleted BOOLEAN NOT NULL, evidence_ref TEXT NOT NULL,
    PRIMARY KEY (revision_id, from_id, link_type, to_id)
);
"""


@dataclass
class _Database:
    schema: str
    dsn: str = field(repr=False)

    def processes(self) -> PostgresProcessRuntimeStore:
        return PostgresProcessRuntimeStore(
            config=PostgresProcessRuntimeStoreConfig(
                dsn=self.dsn, statement_timeout_ms=2_000, connect_timeout_s=3
            )
        )

    def lock(self) -> PostgresAdvisoryResourceLock:
        return PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn=self.dsn, lock_timeout_ms=3_000, connect_timeout_s=3
            )
        )

    def history(self) -> PostgresTopologyHistoryStore:
        return PostgresTopologyHistoryStore(
            config=PostgresTopologyHistoryStoreConfig(
                dsn=self.dsn, statement_timeout_ms=2_000, connect_timeout_s=3
            )
        )


@pytest.fixture
async def database() -> AsyncIterator[_Database]:
    raw = os.environ.get("FDAI_DATABASE_URL")
    if not raw:
        pytest.skip("FDAI_DATABASE_URL is unset; use with-local-test-database.py")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(dsn)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"} or parts.port != 5433:
        pytest.fail("W5 requires the isolated loopback validation PostgreSQL on port 5433")
    schema = "causal_w5_" + uuid4().hex
    scoped = make_conninfo(
        dsn,
        options=f"-c search_path={schema} -c statement_timeout=3000 -c lock_timeout=1000",
        application_name=schema,
        connect_timeout="3",
    )
    async with await psycopg.AsyncConnection.connect(
        make_conninfo(dsn, options="-c statement_timeout=3000 -c lock_timeout=1000"),
        autocommit=True,
        connect_timeout=3,
    ) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            async with await psycopg.AsyncConnection.connect(scoped) as connection:
                await connection.execute(_SCHEMA_SQL)
            yield _Database(schema, scoped)
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            cursor = await admin.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", (schema,)
            )
            assert await cursor.fetchone() == (False,)


class _StaticTelemetryFixture:
    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate
        self.entered = asyncio.Event()
        self.needs: list[TelemetryEvidenceNeed] = []
        self.cancelled = False

    async def gather(self, need: TelemetryEvidenceNeed) -> TelemetryEvidenceReceipt:
        self.needs.append(need)
        self.entered.set()
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        recipe = DEFAULT_TELEMETRY_RECIPE_CATALOG.get(need.recipe_id, need.recipe_version)
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=need.evidence_cutoff,
            disposition=TelemetryEvidenceDisposition.COMPLETE,
            route_count=1,
            queried_route_count=1,
            row_count=1,
            latency_ms=0,
            estimated_cost_units=recipe.estimated_cost_units,
            actual_cost_units=recipe.estimated_cost_units,
            fact_tokens=(f"mechanism:{recipe.mechanism.value}", "source:static-fixture"),
            complete=True,
            truncated=False,
        )


def _investigator(
    database: _Database, provider: _StaticTelemetryFixture, *, deadline: int = 10
) -> ConfiguredAdaptiveTelemetryInvestigator:
    investigator = build_adaptive_telemetry_investigator(
        provider=provider,
        process_store=database.processes(),
        ontology_release=build_ontology_release(),
        object_types=(),
        link_types=(),
        action_types=(),
        interface_types=(),
        function_types=(),
        environment={"FDAI_RCA_ADAPTIVE_TELEMETRY_DEADLINE_SECONDS": str(deadline)},
        resource_lock=database.lock(),
    )
    assert investigator is not None
    return investigator


def _arguments(database: _Database) -> dict:
    return {
        "incident_id": f"fixture:{database.schema}",
        "resource_ref": f"resource:{database.schema}",
        "event_type": "http.429.detected",
        "resource_type": "application",
        "evidence_cutoff": datetime.now(UTC) - timedelta(days=30),
        "correlation_id": f"correlation:{database.schema}",
    }


async def _wait_for_advisory_waiter(connection, schema: str) -> None:
    """Synchronize on PostgreSQL's observed wait, not an assumed scheduling delay."""
    async with asyncio.timeout(2):
        while True:
            cursor = await connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks l JOIN pg_stat_activity a "
                "ON a.pid = l.pid WHERE l.locktype = 'advisory' AND NOT l.granted "
                "AND a.application_name = %s)",
                (schema,),
            )
            if (await cursor.fetchone())[0]:
                return
            await asyncio.sleep(0.01)


async def test_independent_replicas_serialize_and_replay_one_provider_read(database: _Database):
    gate = asyncio.Event()
    providers = (_StaticTelemetryFixture(gate), _StaticTelemetryFixture())
    replicas = tuple(_investigator(database, provider) for provider in providers)
    arguments = _arguments(database)
    async with await psycopg.AsyncConnection.connect(database.dsn, autocommit=True) as observer:
        async with asyncio.TaskGroup() as tasks:
            first = tasks.create_task(replicas[0].investigate(**arguments))
            try:
                await asyncio.wait_for(providers[0].entered.wait(), timeout=3)
                second = tasks.create_task(replicas[1].investigate(**arguments))
                await _wait_for_advisory_waiter(observer, database.schema)
                assert not first.done() and not second.done()
                assert [len(provider.needs) for provider in providers] == [1, 0]
            finally:
                gate.set()
    result = first.result()
    assert second.result() == result
    assert result.investigation.disposition is AdaptiveInvestigationDisposition.HELD
    assert result.investigation.used_queries == 1
    assert result.investigation.execution_authority is False
    assert len(result.investigation.iterations) == 1
    iteration = result.investigation.iterations[0]
    assert len(iteration.frame.active_hypothesis_ids) == 3
    assert iteration.revision is not None
    assert iteration.revision.disposition is AdaptiveInvestigationDisposition.HELD
    assert iteration.revision.active_hypothesis_ids == iteration.frame.active_hypothesis_ids
    assert len(result.citations) == 1
    assert "disposition:complete" in result.citations[0].facts
    assert iteration.revision.evidence_refs == (result.citations[0].ref,)
    assert providers[0].needs[0].evidence_cutoff == arguments["evidence_cutoff"]
    process_id = result.investigation.session_id
    store = database.processes()
    snapshot, events = await store.get(process_id), await store.events(process_id)
    assert snapshot is not None and snapshot.status is ProcessStatus.SUCCEEDED
    assert sum(event.kind is ProcessEventKind.PROCESS_CREATED for event in events) == 1
    assert sum(event.payload.get("record_type") == "adaptive_terminal" for event in events) == 1
    restarted_source = _StaticTelemetryFixture()
    replay = await _investigator(database, restarted_source).investigate(**arguments)
    assert replay == result
    assert not restarted_source.needs
    assert [len(provider.needs) for provider in providers] == [1, 0]
    assert await store.get(process_id) == snapshot
    assert await store.events(process_id) == events


async def test_blocked_query_persists_timeout_and_replays_after_restart(database: _Database):
    provider = _StaticTelemetryFixture(asyncio.Event())
    arguments = _arguments(database)
    result = await _investigator(database, provider, deadline=2).investigate(**arguments)
    assert provider.entered.is_set() and provider.cancelled
    assert len(provider.needs) == 1
    assert result.investigation.disposition is AdaptiveInvestigationDisposition.TIMED_OUT
    assert result.investigation.execution_authority is False
    store, process_id = database.processes(), result.investigation.session_id
    snapshot, events = await store.get(process_id), await store.events(process_id)
    assert snapshot is not None and snapshot.status is ProcessStatus.TIMED_OUT
    terminal = [event for event in events if event.kind is ProcessEventKind.PROCESS_TIMED_OUT]
    assert len(terminal) == 1
    assert terminal[0].payload["result_digest"] == result.investigation.result_digest
    assert sum(event.payload.get("record_type") == "adaptive_terminal" for event in events) == 1
    assert not any(event.kind is ProcessEventKind.PROCESS_CANCELLED for event in events)
    source = _StaticTelemetryFixture()
    assert await _investigator(database, source, deadline=2).investigate(**arguments) == result
    assert not source.needs and len(provider.needs) == 1
    assert await store.get(process_id) == snapshot
    assert await store.events(process_id) == events


async def test_holder_connection_loss_releases_lock_but_not_authority(database: _Database):
    request = ResourceLockAcquisitionRequest.create(
        target_ref=f"resource:{database.schema}",
        action_digest=_RELEASE,
        attempt=1,
        producer_id="fixture-causal-w5",
        producer_version="1.0.0",
        source_revision="commit:" + "a" * 40,
    )
    first, second = database.lock(), database.lock()
    async with await psycopg.AsyncConnection.connect(
        database.dsn, autocommit=True, row_factory=dict_row
    ) as observer:
        async with AsyncExitStack() as stack:
            held = await stack.enter_async_context(first.acquire_evidenced(request))
            assert (await held.assess_ownership()).eligible
            cursor = await observer.execute(
                "SELECT a.pid, a.backend_start FROM pg_stat_activity a "
                "JOIN pg_locks l ON l.pid = a.pid WHERE a.application_name = %s "
                "AND l.locktype = 'advisory' AND l.granted",
                (database.schema,),
            )
            holders = await cursor.fetchall()
            assert len(holders) == 1
            holder = holders[0]
            async with asyncio.TaskGroup() as tasks:

                async def reacquire() -> None:
                    async with second.acquire_evidenced(request) as replacement:
                        assert (await replacement.assess_ownership()).eligible
                        assert replacement.acquisition_receipt.execution_authority is False

                contender = tasks.create_task(reacquire())
                # The wait helper uses tuple rows; the observer otherwise uses dict rows.
                observer.row_factory = psycopg.rows.tuple_row
                await _wait_for_advisory_waiter(observer, database.schema)
                cursor = await observer.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE pid = %s AND backend_start = %s AND application_name = %s",
                    (holder["pid"], holder["backend_start"], database.schema),
                )
                assert await cursor.fetchone() == (True,)
                await asyncio.wait_for(contender, timeout=3)
            with pytest.raises(ResourceLockOwnershipUnknownError, match="readback failed"):
                await held.assess_ownership()
            with pytest.raises(RuntimeError, match="no longer active"):
                held.require_active()
            # Only exit is expected to fail; it must not mask assertions in the body.
            with pytest.raises(ResourceLockReleaseUnknownError, match="session became unusable"):
                await stack.aclose()
        assert held.release_receipt is not None
        assert held.release_receipt.state is ResourceLockReleaseState.UNKNOWN


async def test_bitemporal_history_keeps_exact_cutoffs_tombstones_and_replay(database: _Database):
    start = datetime(2026, 10, 1, tzinfo=UTC)
    t1, t2, t3, t4, t5 = (start + timedelta(hours=i) for i in range(1, 6))
    objects = tuple(
        TopologyObjectRevision(resource, "Resource", "{}", start, start, False, "fixture:baseline")
        for resource in ("resource:a", "resource:b")
    )
    baseline = TopologyRevisionBatch("baseline", "fixture:gen-1", start, start, True, objects)
    link = TopologyLinkRevision(
        "resource:a",
        "Resource",
        "depends_on",
        "resource:b",
        "Resource",
        "{}",
        t1,
        t3,
        False,
        "fixture:late-link",
    )
    late = TopologyRevisionBatch("late", "fixture:gen-2", t1, t3, False, link_revisions=(link,))
    tombstone = replace(link, effective_at=t4, recorded_at=t5, deleted=True)
    deleted = TopologyRevisionBatch(
        "deleted", "fixture:gen-3", t4, t5, False, link_revisions=(tombstone,)
    )
    store = database.history()
    for batch in (baseline, late, deleted):
        await store.append(batch, ontology_release_digest=_RELEASE, source_receipt_digest=_RECEIPT)

    async def view(as_of: datetime, known_at: datetime):
        retained = await database.history().read(as_of=as_of, known_at=known_at)
        return graph_at(retained, as_of=as_of, known_at=known_at)

    early = await view(t1, t2)
    assert early.complete and not early.graph.links
    assert early.revision_ids == ("baseline",)
    assert not (await view(t1 - timedelta(microseconds=1), t3)).graph.links
    learned = await view(t1, t3)
    assert learned.complete and len(learned.graph.links) == 1
    assert learned.graph.links[0].from_id == "resource:a"
    assert learned.graph.links[0].to_id == "resource:b"
    assert learned.revision_ids == ("baseline", "late")
    assert learned.ontology_release_digests == (_RELEASE,)
    assert learned.source_receipt_digests == (_RECEIPT,)
    assert "fixture:late-link" in learned.evidence_refs
    assert len((await view(t4, t5 - timedelta(microseconds=1))).graph.links) == 1
    removed = await view(t4, t5)
    assert removed.complete and not removed.graph.links
    assert removed.revision_ids == ("baseline", "late", "deleted")
    assert {item.id for item in removed.graph.objects} == {"resource:a", "resource:b"}
    assert await view(t1, t2) == early
    assert len((await view(t1, t5)).graph.links) == 1
    t6 = start + timedelta(hours=6)
    await store.append(
        TopologyRevisionBatch("new-baseline", "fixture:gen-4", t6, t6, True),
        ontology_release_digest=_RELEASE,
        source_receipt_digest=_RECEIPT,
    )
    current = await view(t6, t6)
    assert current.complete and not current.graph.objects and not current.graph.links
    assert current.revision_ids == ("new-baseline",)
    assert len((await view(t1, t6)).graph.links) == 1
    assert await view(t1, t2) == early
    await store.append(late, ontology_release_digest=_RELEASE, source_receipt_digest=_RECEIPT)
    assert await view(t1, t3) == learned
    with pytest.raises(ValueError, match="replay does not match"):
        await store.append(
            replace(late, provider_generation_ref="fixture:conflicting-generation"),
            ontology_release_digest=_RELEASE,
            source_receipt_digest=_RECEIPT,
        )
    assert await view(t1, t3) == learned
