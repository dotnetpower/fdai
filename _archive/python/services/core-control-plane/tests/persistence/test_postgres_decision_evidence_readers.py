"""PostgreSQL integration tests for decision evidence readers and ontology gates."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.workflow import OntologyFunctionGateEvaluator
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.control_loop_support import build_ontology_gate_reader
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryStateStore
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=4)


def _catalog():
    return load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )


@asynccontextmanager
async def _postgres_decision_fixture() -> AsyncIterator[tuple[PostgresOntologyInstanceStore, str]]:
    raw_dsn = os.environ.get("FDAI_DATABASE_URL")
    if not raw_dsn:
        pytest.skip("FDAI_DATABASE_URL is unset; use with-local-test-database.py")
    dsn = raw_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("decision evidence Postgres test requires a loopback database")
    catalog = _catalog()
    schema = "decision_gate_" + uuid.uuid4().hex[:12]
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f"CREATE SCHEMA {schema}")
        try:
            scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
            async with await psycopg.AsyncConnection.connect(scoped) as conn:
                await conn.execute(
                    "CREATE TABLE ontology_resource (id TEXT PRIMARY KEY, "
                    "object_type TEXT NOT NULL, properties JSONB NOT NULL, "
                    "revision BIGINT NOT NULL, type_version TEXT NOT NULL, "
                    "catalog_digest TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW());"
                    "CREATE TABLE ontology_link_type (name TEXT PRIMARY KEY);"
                    "CREATE TABLE ontology_link (link_type TEXT NOT NULL, "
                    "from_id TEXT REFERENCES ontology_resource(id), "
                    "to_id TEXT REFERENCES ontology_resource(id), properties JSONB NOT NULL, "
                    "type_version TEXT NOT NULL, catalog_digest TEXT NOT NULL, "
                    "PRIMARY KEY(from_id, link_type, to_id));"
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                    "updated_at TIMESTAMPTZ DEFAULT NOW());"
                    "CREATE TABLE inventory_snapshot (id TEXT PRIMARY KEY, "
                    "scopes JSONB NOT NULL DEFAULT '[]'::jsonb, "
                    "metadata JSONB NOT NULL DEFAULT '{}'::jsonb, "
                    "started_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"
                    "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, "
                    "snapshot_id TEXT NOT NULL);"
                    "CREATE TABLE inventory_observation_partition ("
                    "scope_ref TEXT PRIMARY KEY, state TEXT NOT NULL, "
                    "last_watermark BIGINT NOT NULL DEFAULT 0);"
                    "CREATE TABLE inventory_observation_journal ("
                    "watermark BIGSERIAL PRIMARY KEY, "
                    "subject_kind TEXT NOT NULL, scope_ref TEXT NOT NULL, "
                    "subject_ref TEXT NOT NULL, subject_type TEXT NOT NULL, "
                    "properties JSONB NOT NULL DEFAULT '{}'::jsonb, operation TEXT, "
                    "operation_status TEXT, mutation_kind TEXT NOT NULL, "
                    "observation_kind TEXT NOT NULL, effective_at TIMESTAMPTZ NOT NULL, "
                    "recorded_at TIMESTAMPTZ NOT NULL, source_identity TEXT NOT NULL, "
                    "source_revision TEXT, "
                    "source_event_id TEXT NOT NULL, observation_id TEXT NOT NULL, "
                    "content_digest TEXT NOT NULL)"
                )
                for lt in catalog.link_types:
                    await conn.execute(
                        "INSERT INTO ontology_link_type(name) VALUES (%s)", (lt.name,)
                    )
            store = PostgresOntologyInstanceStore(
                config=PostgresOntologyInstanceStoreConfig(dsn=scoped),
                object_types=catalog.object_types,
                link_types=catalog.link_types,
            )
            yield store, scoped
        finally:
            await admin.execute(f"DROP SCHEMA {schema} CASCADE")


def _metadata(cutoff: datetime = NOW) -> dict[str, object]:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-1",
        effective_at=cutoff,
        recorded_at=cutoff,
        evidence_cutoff=cutoff,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-generation:generation-1",),
    ).to_mapping()


async def _seed_graph(store: PostgresOntologyInstanceStore, *, cutoff: datetime = NOW) -> None:
    long_ago = NOW - timedelta(days=30)
    objects = (
        OntologyObjectRecord(
            id="db-1",
            object_type="Resource",
            properties={
                "id": "db-1",
                "type": "compute",
                "properties": {STATE_FACT_METADATA_PROPERTY: _metadata(cutoff)},
            },
        ),
        OntologyObjectRecord(
            id="wl-1",
            object_type="Workload",
            properties={
                "id": "wl-1",
                "name": "wl-1",
                "workload_kind": "service",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
        OntologyObjectRecord(
            id="svc-1",
            object_type="BusinessService",
            properties={
                "id": "svc-1",
                "name": "svc-1",
                "criticality": "low",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        ),
        OntologyObjectRecord(
            id="win-1",
            object_type="ChangeWindow",
            properties={
                "id": "win-1",
                "window_kind": "maintenance",
                "scope_ref": "db-1",
                "status": "approved",
                "effective_from": NOW - timedelta(hours=1),
                "effective_to": NOW + timedelta(hours=2),
                "policy_ref": "policy-1",
            },
        ),
        OntologyObjectRecord(
            id="plan-1",
            object_type="RecoveryPlan",
            properties={
                "id": "plan-1",
                "strategy": "rollback",
                "status": "ready",
                "workflow_ref": "change-risk-gated-scale-in@1.0.0",
                "action_type_refs": ["ops.scale-in@1.0.0"],
                "compensation_order": ["scale_out"],
                "impact_envelope_id": "env-1",
                "recovery_objective_ref": "obj-1",
                "verification_probes": ["target_healthy"],
                "last_rehearsed_at": EARLIER,
                "expires_at": NOW + timedelta(days=7),
            },
        ),
        OntologyObjectRecord(
            id="run-1",
            object_type="ActionRun",
            properties={
                "id": "run-1",
                "action_type_ref": "ops.scale-in",
                "action_type_version": "1.0.0",
                "target_ref": "db-1",
                "status": "dispatched",
                "mode": "shadow",
                "idempotency_key": "run-1",
                "started_at": EARLIER,
                "ended_at": EARLIER,
            },
        ),
    )
    links = (
        OntologyLinkRecord(link_type="workload_runs_on", from_id="wl-1", to_id="db-1"),
        OntologyLinkRecord(link_type="implemented_by", from_id="svc-1", to_id="wl-1"),
        OntologyLinkRecord(link_type="recovery_targets_resource", from_id="plan-1", to_id="db-1"),
    )
    await store.replace_subgraph(objects=objects, links=links)


async def test_postgres_decision_readers_open_and_close_gates_on_committed_sql() -> None:
    catalog = _catalog()
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=operational_function_types(catalog.function_types),
    )
    async with _postgres_decision_fixture() as (store, dsn):
        await _seed_graph(store)
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            await conn.execute(
                "INSERT INTO inventory_snapshot (id, scopes, started_at) "
                "VALUES (%s, %s::jsonb, %s)",
                ("generation-1", json.dumps(["scope-1"]), NOW),
            )
            await conn.execute(
                "INSERT INTO inventory_active (singleton, snapshot_id) VALUES (TRUE, %s)",
                ("generation-1",),
            )
            for k, v in (
                (
                    "inventory-ontology:status",
                    {"status": "available", "generation": "generation-1", "complete": True},
                ),
                (
                    "inventory-ontology:manifest",
                    {
                        "generation": "generation-1",
                        "complete": True,
                        "relationship_complete": True,
                        "dropped_reasons": [],
                    },
                ),
            ):
                await conn.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                    (k, json.dumps(v)),
                )
            await conn.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                (
                    "arg_resource_change_cursor:scope-1",
                    json.dumps(
                        {
                            "complete": True,
                            "last_polled_at": NOW.isoformat(),
                            "pending_event_ids": [],
                        }
                    ),
                ),
            )
            await conn.execute(
                "INSERT INTO inventory_observation_journal "
                "(subject_kind, scope_ref, subject_ref, subject_type, properties, operation, "
                "operation_status, mutation_kind, observation_kind, effective_at, recorded_at, "
                "source_identity, source_event_id, observation_id, content_digest) "
                "VALUES ('object', 'scope-1', 'db-1', 'compute', '{}'::jsonb, 'write', "
                "'Succeeded', 'upsert', 'change_hint', %s, %s, %s, 'ev-1', 'obs-1', %s)",
                (
                    EARLIER,
                    EARLIER,
                    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                    "sha256:" + "1" * 64,
                ),
            )

        bound = build_ontology_gate_reader(
            catalog_root=REPO_ROOT / "rule-catalog",
            ontology_store=store,
            ontology_release=release,
            audit_store=InMemoryStateStore(),
            environment={"FDAI_STATE_STORE_DSN": dsn, "FDAI_INVENTORY_SCOPES": "scope-1"},
            clock=lambda: NOW,
        )
        assert bound is not None
        evaluator = OntologyFunctionGateEvaluator(reader=bound[0], max_reading_age=bound[1])

        assert (
            await evaluator.evaluate_context(
                rule_id="ontology-function:decision.blast_radius",
                step_id="gate",
                process_id="p-1",
                target_resource_id="db-1",
                at=NOW,
            )
            is True
        )
        assert (
            await evaluator.evaluate_context(
                rule_id="ontology-function:decision.change_risk",
                step_id="gate",
                process_id="p-1",
                target_resource_id="db-1",
                at=NOW,
            )
            is True
        )

        # Unverified change cursor closes change_risk gate on Postgres
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            await conn.execute(
                "UPDATE state_kv SET value = %s::jsonb WHERE key = %s",
                (
                    json.dumps(
                        {
                            "complete": False,
                            "last_polled_at": NOW.isoformat(),
                            "pending_event_ids": ["pending-1"],
                        }
                    ),
                    "arg_resource_change_cursor:scope-1",
                ),
            )
        assert (
            await evaluator.evaluate_context(
                rule_id="ontology-function:decision.change_risk",
                step_id="gate",
                process_id="p-1",
                target_resource_id="db-1",
                at=NOW,
            )
            is False
        )
