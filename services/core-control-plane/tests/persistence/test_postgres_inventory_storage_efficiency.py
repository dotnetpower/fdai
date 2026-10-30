"""Deterministic membership/body sharing checks that need no PostgreSQL service."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence import postgres_inventory_shared_membership as shared
from fdai.delivery.persistence.postgres_inventory_observation_records import snapshot_records
from fdai.delivery.persistence.postgres_inventory_shared_properties import (
    factor_properties,
    prune_shared_properties,
    share_property_rows,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import _member_values
from fdai.delivery.persistence.postgres_inventory_snapshot_support import stage_snapshot_batch
from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 10, 30, 2, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]
MIGRATION = (
    "service-migrations/branches/core-control-plane/versions/"
    "20261030_core_inventory_storage_efficiency.py"
)


def records(generation: str, *, at: datetime = NOW, count: int = 32, state: str = "running"):
    return snapshot_records(
        PromotedInventoryObservation(
            generation=generation,
            recorded_at=at + timedelta(seconds=2),
            resources=tuple(
                ResourceRecord(
                    resource_id=f"resource-{index:04}",
                    type="compute.vm",
                    last_seen=at.isoformat(),
                    props={
                        "state": state,
                        STATE_FACT_METADATA_PROPERTY: {
                            "state": {
                                "effective_at": at.isoformat(),
                                "recorded_at": (at + timedelta(seconds=2)).isoformat(),
                                "evidence_cutoff": at.isoformat(),
                                "source_identity": "provider:principal-a",
                                "source_revision": generation,
                                "evidence_refs": ["receipt:principal-a", generation],
                            }
                        },
                    },
                )
                for index in range(count)
            ),
            links=(),
            complete=True,
        ),
        scope_refs=("scope-test",),
    )


def pack(observations):
    return shared.pack_membership(
        tuple(_member_values(item.source_revision, item) for item in observations),
        generation_id=observations[0].source_revision,
        recorded_at=observations[0].recorded_at,
    )


def expand(packed: shared.SharedMembership) -> list[dict[str, Any]]:
    """Reference JSON-path expansion, including numeric keys and marker-shaped input."""
    assert shared.content_digest(packed.root_body) == packed.root_digest
    root = json.loads(packed.root_body)
    bindings = json.loads(packed.bindings)
    rows = []
    for _, member_digest, evidence_digest in root["pages"]:
        body = packed.pages[member_digest]
        evidence_body = packed.pages[evidence_digest]
        assert shared.content_digest(body) == member_digest
        assert shared.content_digest(evidence_body) == evidence_digest
        for stable, template in zip(json.loads(body), json.loads(evidence_body), strict=True):
            member = stable | template["body"]
            for substitution in template["substitutions"]:
                path = substitution["path"]
                parent = member
                for key in path[:-1]:
                    parent = parent[int(key)] if isinstance(parent, list) else parent[key]
                leaf = int(path[-1]) if isinstance(parent, list) else path[-1]
                parent[leaf] = bindings[substitution["binding"]]
            member["generation_id"] = bindings["generation_id"]
            member["observed_at"] = datetime.fromisoformat(member["observed_at"])
            rows.append(member)
    assert len(rows) == root["count"]
    return sorted(rows, key=lambda row: (row["subject_kind"], row["subject_ref"]))


def test_unchanged_generations_share_exact_pages_and_preserve_every_clock() -> None:
    first = pack(records("generation-0"))
    for index in range(1, 20):
        observations = records(f"generation-{index}", at=NOW + timedelta(minutes=index))
        current = pack(observations)
        assert current.root_digest == first.root_digest
        assert current.pages == first.pages
        expanded = expand(current)
        for row, observation in zip(expanded, observations, strict=True):
            expected = _member_values(observation.source_revision, observation)
            assert row["observed_at"] == expected[7]
            assert row["freshness_properties"] == json.loads(str(expected[8]))


def test_changed_subject_and_deletion_copy_only_affected_pages_without_replay_chain() -> None:
    observations = records("generation-0", count=512)
    original = pack(observations)
    changed = list(observations)
    member_values = [_member_values(item.source_revision, item) for item in changed]
    changed_member = list(member_values[100])
    changed_member[4] = "sha256:" + "f" * 64
    member_values[100] = tuple(changed_member)
    updated = shared.pack_membership(
        member_values, generation_id="generation-0", recorded_at=observations[0].recorded_at
    )
    assert len(set(updated.pages) - set(original.pages)) == 1
    assert len(set(original.pages) - set(updated.pages)) == 1
    deleted = shared.pack_membership(
        member_values[:-1], generation_id="generation-0", recorded_at=observations[0].recorded_at
    )
    assert len(expand(original)) == 512
    assert len(expand(updated)) == 512
    assert len(expand(deleted)) == 511
    assert not any(row["subject_ref"] == observations[-1].subject_ref for row in expand(deleted))
    assert all(
        value in deleted.pages
        for _, member_digest, evidence_digest in json.loads(deleted.root_body)["pages"]
        for value in (member_digest, evidence_digest)
    )


def test_membership_preserves_nonuniform_time_principal_evidence_and_marker_values() -> None:
    observations = records("generation-0", count=2)
    values = [_member_values(item.source_revision, item) for item in observations]
    changed = list(values[1])
    changed[7] = NOW - timedelta(seconds=41)
    evidence = {
        STATE_FACT_METADATA_PROPERTY: {
            "0": [{"path": ["not", "a", "marker"], "binding": "observed_at"}],
            "clock": NOW.isoformat(),
            "principal": "provider:principal-b",
            "effective_at": (NOW - timedelta(days=1)).isoformat(),
        }
    }
    changed[8] = shared.canonical_json(evidence)
    values[1] = tuple(changed)
    packed = shared.pack_membership(
        values, generation_id="generation-0", recorded_at=observations[0].recorded_at
    )
    restored = expand(packed)[1]
    assert restored["observed_at"] == changed[7]
    assert restored["freshness_properties"] == evidence
    assert pack(observations).root_digest != packed.root_digest
    assert packed == shared.pack_membership(
        list(reversed(values)),
        generation_id="generation-0",
        recorded_at=observations[0].recorded_at,
    )


def test_alias_bindings_preserve_z_and_offset_spellings_without_normalizing_evidence() -> None:
    observation = records("generation-0", count=1)[0]
    member = list(_member_values(observation.source_revision, observation))
    evidence = {
        STATE_FACT_METADATA_PROPERTY: {
            "z": NOW.isoformat().replace("+00:00", "Z"),
            "offset": NOW.isoformat(),
            "recorded_z": observation.recorded_at.isoformat().replace("+00:00", "Z"),
            "other_offset": NOW.astimezone(timezone(timedelta(hours=9))).isoformat(),
        }
    }
    member[8] = shared.canonical_json(evidence)
    packed = shared.pack_membership(
        (tuple(member),),
        generation_id=observation.source_revision,
        recorded_at=observation.recorded_at,
    )
    assert expand(packed)[0]["freshness_properties"] == evidence
    bindings = json.loads(packed.bindings)
    assert bindings["observed_at"] != bindings["observed_at_z"]
    assert bindings["observed_at_z"].endswith("Z")


def test_unique_per_generation_receipts_do_not_duplicate_stable_membership() -> None:
    observations = records("generation-0", count=64)
    original = pack(observations)
    values = []
    for observation in observations:
        member = list(_member_values(observation.source_revision, observation))
        properties = json.loads(str(member[8]))
        properties[STATE_FACT_METADATA_PROPERTY]["state"]["evidence_refs"] = [
            f"receipt:independent-new-observation:{observation.subject_ref}"
        ]
        member[8] = shared.canonical_json(properties)
        values.append(tuple(member))
    changed = shared.pack_membership(
        values, generation_id="generation-0", recorded_at=observations[0].recorded_at
    )
    prior_pages = json.loads(original.root_body)["pages"]
    new_pages = json.loads(changed.root_body)["pages"]
    assert [page[1] for page in prior_pages] == [page[1] for page in new_pages]
    assert [page[2] for page in prior_pages] != [page[2] for page in new_pages]
    assert expand(changed)[0]["freshness_properties"] != expand(original)[0]["freshness_properties"]


def test_relationship_members_keep_endpoints_and_independent_evidence_clocks() -> None:
    member = list(_member_values("generation-0", records("generation-0", count=1)[0]))
    member[1:4] = ["relationship", "resource-a:depends_on:resource-b", "depends_on"]
    member[9:] = ["resource-a", "compute.vm", "depends_on", "resource-b", "database.postgres"]
    evidence = {
        "relationship_observation": {
            "effective_at": (NOW - timedelta(minutes=3)).isoformat(),
            "recorded_at": (NOW - timedelta(minutes=1)).isoformat(),
            "evidence_cutoff": (NOW - timedelta(minutes=2)).isoformat(),
            "principal": "observer:principal-b",
        }
    }
    member[8] = shared.canonical_json(evidence)
    packed = shared.pack_membership((tuple(member),), generation_id="generation-0", recorded_at=NOW)
    restored = expand(packed)[0]
    assert restored["from_id"] == "resource-a"
    assert restored["to_type"] == "database.postgres"
    assert restored["freshness_properties"] == evidence


def test_packed_logical_bytes_and_rows_are_lower_on_the_same_workload() -> None:
    pages = {}
    roots = {}
    binding_bytes = 0
    legacy_bytes = 0
    for index in range(20):
        observations = records(f"generation-{index}", at=NOW + timedelta(minutes=index), count=512)
        current = pack(observations)
        pages.update(current.pages)
        roots[current.root_digest] = current.root_body
        binding_bytes += len(
            shared.canonical_json(
                [observations[0].source_revision, current.root_digest, json.loads(current.bindings)]
            ).encode("utf-8")
        )
        for item in observations:
            values = _member_values(item.source_revision, item)
            legacy_bytes += len(
                shared.canonical_json(
                    [
                        value.isoformat() if isinstance(value, datetime) else value
                        for value in values
                    ]
                ).encode("utf-8")
            )
    packed_bytes = binding_bytes + sum(
        len(body.encode("utf-8")) for body in (*pages.values(), *roots.values())
    )
    assert len(roots) == 1
    assert len(pages) < 512
    assert len(pages) + len(roots) + 20 < 512 * 20 // 10
    assert packed_bytes < legacy_bytes // 5
    print(
        f"membership logical bytes: legacy={legacy_bytes} shared={packed_bytes}; "
        f"rows: legacy={512 * 20} shared={len(pages) + len(roots) + 20}"
    )


def test_membership_page_bounds_and_empty_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared, "MAX_PAGE_MEMBERS", 1)
    packed = pack(records("generation-0", count=32))
    assert all(len(json.loads(body)) == 1 for body in packed.pages.values())
    assert len(expand(packed)) == 32
    empty = shared.pack_membership((), generation_id="empty", recorded_at=NOW)
    assert expand(empty) == []
    assert empty.pages == {}
    with pytest.raises(ValueError, match="duplicate subject"):
        pack(records("generation-0", count=1) * 2)
    monkeypatch.setattr(shared, "MAX_PAGE_BYTES", 1)
    with pytest.raises(ValueError, match="page exceeds"):
        pack(records("generation-0", count=1))


def test_properties_share_bodies_not_clock_or_principal_evidence() -> None:
    original = {
        "state": "running",
        "payload": "a" * 8192,
        STATE_FACT_METADATA_PROPERTY: {"clock": NOW.isoformat(), "principal": "principal-a"},
    }
    changed = {
        **original,
        STATE_FACT_METADATA_PROPERTY: {
            "clock": (NOW + timedelta(minutes=1)).isoformat(),
            "principal": "principal-b",
        },
    }
    digest, body, evidence = factor_properties(original)
    new_digest, new_body, new_evidence = factor_properties(changed)
    assert (digest, body) == (new_digest, new_body)
    assert evidence != new_evidence
    assert json.loads(body) | evidence == original
    assert json.loads(new_body) | new_evidence == changed
    assert factor_properties({})[2] == {}
    actual = len(body.encode()) + 20 * (len(digest) + len(shared.canonical_json(evidence).encode()))
    legacy = 20 * len(shared.canonical_json(original).encode())
    assert actual < legacy // 10
    print(f"properties logical bytes: legacy={legacy} shared={actual}")


def test_real_metadata_producer_z_clocks_round_trip_and_share_stable_content() -> None:
    bodies = {}
    evidence_bytes = 0
    legacy_bytes = 0
    initial_pages = None
    roots = set()
    membership_pages = {}
    membership_roots = {}
    membership_bindings_bytes = 0
    membership_legacy_bytes = 0
    for generation_index in range(12):
        generation = f"producer-generation-{generation_index}"
        at = NOW + timedelta(minutes=generation_index)

        def fact(index: int, *, at=at, generation=generation) -> StateFactMetadata:
            return StateFactMetadata(
                lane=StateFactLane.OBSERVED,
                authority=StateFactAuthority.PROVIDER,
                source_identity="provider:inventory",
                source_revision=generation,
                effective_at=at,
                recorded_at=at + timedelta(seconds=2),
                evidence_cutoff=at,
                freshness_ceiling_seconds=300,
                completeness=1.0,
                synthetic=False,
                evidence_refs=(f"receipt:resource-{index}",),
            )

        resources = tuple(
            ResourceRecord(
                resource_id=f"resource-{index:04}",
                type="compute.vm",
                last_seen=at.isoformat(),
                props={
                    "ordinal": index,
                    "payload": "x" * 8192,
                    STATE_FACT_METADATA_PROPERTY: {"state": fact(index).to_mapping()},
                },
            )
            for index in range(32)
        )
        link_metadata = LinkObservationMetadata(
            state_fact=fact(0),
            verification_method="deterministic-cross-check",
            verified=True,
            verifier_identity="inventory.endpoint-verifier",
            verifier_revision="1.0.0",
            verification_receipt_ref="sha256:" + "1" * 64,
            inventory_generation=generation,
            mapping_id="provider.depends-on",
            mapping_revision="1.0.0",
            source_schema_version="provider@1.0.0",
            source_schema_digest="sha256:" + "2" * 64,
        )
        observation = PromotedInventoryObservation(
            generation=generation,
            resources=resources,
            links=(
                LinkRecord(
                    from_id="resource-0000",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="resource-0001",
                    to_type="compute.vm",
                    observation_metadata=link_metadata,
                ),
            ),
            complete=True,
            recorded_at=at + timedelta(seconds=2),
        )
        normalized = snapshot_records(observation, scope_refs=("scope-test",))
        packed = pack(normalized)
        roots.add(packed.root_digest)
        membership_pages.update(packed.pages)
        membership_roots[packed.root_digest] = packed.root_body
        membership_bindings_bytes += len(
            shared.canonical_json([generation, packed.root_digest, packed.bindings]).encode()
        )
        for item in normalized:
            membership_legacy_bytes += len(
                shared.canonical_json(
                    [
                        value.isoformat() if isinstance(value, datetime) else value
                        for value in _member_values(item.source_revision, item)
                    ]
                ).encode()
            )
        stable_pages = [page[1] for page in json.loads(packed.root_body)["pages"]]
        if initial_pages is None:
            initial_pages = stable_pages
        assert stable_pages == initial_pages
        restored = {(row["subject_kind"], row["subject_ref"]): row for row in expand(packed)}
        for item in normalized:
            key = (
                STATE_FACT_METADATA_PROPERTY
                if item.subject_kind.value == "object"
                else LINK_OBSERVATION_METADATA_PROPERTY
            )
            assert restored[(item.subject_kind.value, item.subject_ref)][
                "freshness_properties"
            ] == {key: item.properties[key]}
        assert fact(0).to_mapping()["effective_at"].endswith("Z")
        for resource in resources:
            properties = dict(resource.props)
            digest, body, evidence = factor_properties(properties)
            bodies[digest] = body
            legacy_bytes += len(shared.canonical_json(properties).encode())
            evidence_bytes += len(digest) + len(shared.canonical_json(evidence).encode())
    stored_bytes = evidence_bytes + sum(len(body.encode()) for body in bodies.values())
    membership_stored_bytes = membership_bindings_bytes + sum(
        len(body.encode()) for body in (*membership_pages.values(), *membership_roots.values())
    )
    assert len(roots) == 1
    assert membership_stored_bytes < membership_legacy_bytes // 3
    assert stored_bytes < legacy_bytes // 4
    print(
        f"real producer Z property bytes: legacy={legacy_bytes} shared={stored_bytes}; "
        f"membership roots={len(roots)}, stable membership pages reused"
    )
    print(
        f"real producer Z membership bytes: legacy={membership_legacy_bytes} "
        f"shared={membership_stored_bytes}"
    )


async def test_shared_body_write_and_orphan_cleanup_are_bounded_and_locked() -> None:
    cursor = MagicMock()
    cursor.executemany = AsyncMock()
    cursor.rowcount = 7
    cursor.fetchone = AsyncMock(
        side_effect=[{"available": True}, {"available": True}, {"acquired": True}]
    )
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connection.execute = AsyncMock(return_value=cursor)
    properties = {"payload": "same"}
    rows = await share_property_rows(connection, [{"props": properties}, {"props": properties}])
    assert len(rows) == 2
    assert len(cursor.executemany.await_args.args[1]) == 1
    assert "pg_advisory_xact_lock_shared" in connection.execute.await_args_list[1].args[0]
    assert await prune_shared_properties(connection, limit=7, max_bytes=1024) == 7
    query, parameters = connection.execute.await_args.args
    assert parameters == (7, 1024)
    assert "NOT EXISTS" in query and "SKIP LOCKED" in query and "SUM(bytes)" in query
    with pytest.raises(ValueError, match="exceeds"):
        await prune_shared_properties(connection, limit=1001)


async def test_property_cleanup_skips_busy_storage_without_deleting() -> None:
    cursor = MagicMock()
    cursor.fetchone = AsyncMock(side_effect=[{"available": True}, {"acquired": False}])
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=cursor)
    assert await prune_shared_properties(connection) == 0
    assert connection.execute.await_count == 2


async def test_staging_writes_shared_references_with_compact_bounded_parameters() -> None:
    properties = {
        "state": "running",
        "payload": "x" * 8192,
        STATE_FACT_METADATA_PROPERTY: {"clock": NOW.isoformat(), "principal": "principal-a"},
    }
    batch = InventoryBatch(
        resources=(
            ResourceRecord(resource_id="resource-a", type="compute.vm", props=properties),
            ResourceRecord(resource_id="resource-b", type="compute.vm", props=properties),
        ),
        links=(
            LinkRecord(
                from_id="resource-a",
                from_type="compute.vm",
                link_type="depends_on",
                to_id="resource-b",
                to_type="compute.vm",
                link_props=properties,
            ),
        ),
    )
    cursor = MagicMock()
    cursor.executemany = AsyncMock()
    cursor.rowcount = 2
    cursor.fetchone = AsyncMock(return_value={"available": True})
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connection.execute = AsyncMock(return_value=cursor)
    await stage_snapshot_batch(
        connection, attempt_id="generation-0", batch=batch, write_batch_size=100
    )
    inserts = [
        call.args
        for call in connection.execute.await_args_list
        if call.args[0].startswith("INSERT INTO inventory_snapshot_")
    ]
    assert len(inserts) == 2
    assert "inventory_snapshot_resource_row" in inserts[0][0]
    assert "inventory_snapshot_link_row" in inserts[1][0]
    assert "NULL, item.provider_ref" in inserts[0][0]
    assert "item.to_id, item.to_type, NULL" in inserts[1][0]
    for _, parameters in inserts:
        parameter = parameters[0]
        assert len(parameter.dumps(parameter.obj).encode("utf-8")) < 4 * 1024 * 1024
        for row in parameter.obj:
            assert "props" not in row
            assert row["props_freshness"] == {
                STATE_FACT_METADATA_PROPERTY: properties[STATE_FACT_METADATA_PROPERTY]
            }
    assert all(len(call.args[1]) == 1 for call in cursor.executemany.await_args_list)


async def test_namespace_mismatch_denies_shared_writes_and_skips_cleanup() -> None:
    cursor = MagicMock()
    cursor.fetchone = AsyncMock(return_value={"available": False})
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=cursor)
    with pytest.raises(ValueError, match="logical inventory schema"):
        await share_property_rows(connection, [{"props": {"state": "running"}}])
    with pytest.raises(ValueError, match="logical inventory schema"):
        await shared.require_membership_namespace(connection)
    assert await prune_shared_properties(connection) == 0
    for call in connection.execute.await_args_list:
        assert "backing.relnamespace=logical.relnamespace" in call.args[0]
        assert "inventory_snapshot_resource" in call.args[0]
        assert not call.args[0].startswith(("INSERT", "DELETE"))


def test_database_fixture_repr_does_not_expose_connection_data() -> None:
    from tests.persistence.test_postgres_inventory_storage_efficiency_db import StorageDatabase

    fixture = StorageDatabase(dsn="synthetic-private-connection-marker", schema="test_schema")
    assert "synthetic-private-connection-marker" not in repr(fixture)
    assert "dsn=" not in repr(fixture)


def migration_statements(path: str, direction: str) -> tuple[Any, list[str]]:
    specification = importlib.util.spec_from_file_location(
        "inventory_storage_migration", ROOT / path
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    statements: list[str] = []
    module.op = SimpleNamespace(execute=statements.append)
    getattr(module, direction)()
    return module, statements


def test_migration_preserves_guards_and_materializes_before_rollback() -> None:
    migration, statements = migration_statements(MIGRATION, "upgrade")
    assert migration.revision == "core_inventory_storage_efficiency_20261030"
    assert migration.down_revision == "core_cache_storage_efficiency_20261030"
    assert len(migration.revision) == 42
    sql = "\n".join(statements)
    assert "# noqa" not in sql
    assert "DROP TRIGGER" not in sql
    assert "DELETE FROM inventory_observation" not in sql
    assert "RENAME TO inventory_observation_snapshot_member_legacy" in sql
    assert "storage_schema_version=2" in sql
    assert "membership page is unavailable" in sql
    assert "BEFORE UPDATE ON inventory_observation_snapshot_page" in sql
    _, statements = migration_statements(MIGRATION, "downgrade")
    sql = "\n".join(statements)
    assert sql.index("INSERT INTO inventory_observation_snapshot_member_legacy") < sql.index(
        "DROP VIEW inventory_observation_snapshot_member"
    )
    assert sql.index("SET props=content.body") < sql.index(
        "DROP TABLE inventory_snapshot_properties"
    )


def test_migration_uses_literal_metadata_and_sql_for_ownership_review(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "service-migrations"))
    from service_migrations.inventory import load_revision_metadata

    metadata = load_revision_metadata(ROOT / MIGRATION)
    assert metadata.rollback["restores"] == "core_cache_storage_efficiency_20261030"
    assert set(metadata.created_tables) == {
        "inventory_snapshot_properties",
        "inventory_observation_snapshot_page",
        "inventory_observation_snapshot_set",
        "inventory_observation_snapshot_binding",
    }
    assert {
        "inventory_snapshot_resource_row",
        "inventory_snapshot_link_row",
        "inventory_observation_snapshot_member_legacy",
    } <= set(metadata.touched_tables)


def test_migration_coordinator_reads_all_three_new_revisions_without_database() -> None:
    result = subprocess.run(  # noqa: S603 - fixed read-only repository metadata command
        [sys.executable, str(ROOT / "service-migrations/migrate.py"), "all", "validate"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())
    revisions = {}
    for path in (ROOT / MIGRATION).parent.glob("20261030_core_*_storage_efficiency.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}
        }
        revisions[values["revision"]] = values["down_revision"]
    assert revisions["core_inventory_storage_efficiency_20261030"] == (
        "core_cache_storage_efficiency_20261030"
    )
    assert revisions["core_state_storage_efficiency_20261030"] == (
        "core_inventory_storage_efficiency_20261030"
    )


def test_migration_bounds_lock_waits_and_rejects_dependent_views_before_ddl() -> None:
    _, statements = migration_statements(MIGRATION, "upgrade")
    first = statements[0]
    assert "SET LOCAL statement_timeout = '15s'" in first
    assert "SET LOCAL lock_timeout = '2s'" in first
    assert "IN ACCESS EXCLUSIVE MODE" in first
    assert "pg_catalog.pg_depend" in first and "pg_catalog.pg_rewrite" in first
    assert "dependent.relkind IN ('v', 'm')" in first
    assert "inventory storage efficiency migration has unsupported view dependency" in first
    for table in (
        "inventory_snapshot_resource",
        "inventory_snapshot_link",
        "inventory_observation_snapshot_member",
    ):
        assert f"'{table}'::regclass" in first
    assert "CREATE TABLE" not in first and "ALTER TABLE" not in first
    sql = "\n".join(statements)
    assert "CASCADE" not in sql
    assert "SECURITY DEFINER" not in sql
    assert sql.count("SECURITY INVOKER") == 3
    assert sql.count("SET search_path = pg_catalog, %I, pg_temp") == 3
    assert "TO fdai_operator" not in sql
    _, statements = migration_statements(MIGRATION, "downgrade")
    assert "SET LOCAL statement_timeout = '15s'" in statements[0]
    assert "SET LOCAL lock_timeout = '2s'" in statements[0]
