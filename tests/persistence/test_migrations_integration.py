"""Integration test - runs ``alembic upgrade head`` against a live Postgres.

Skipped unless ``FDAI_DATABASE_URL`` is set. The docker-compose dev
stack (``make dev-up``) exposes the URL as
``postgresql+psycopg://fdai:devonly@localhost:5432/fdai``.

The test:

1. Runs ``alembic upgrade head`` against the live DB.
2. Verifies every declared table exists.
3. Verifies the pgvector extension is installed.
4. Verifies the HNSW index on ``ontology_embedding`` is present.
5. Downgrades back to ``base`` and asserts tables are gone.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "alembic_version",
    "ontology_object_type",
    "ontology_link_type",
    "ontology_resource",
    "ontology_finding",
    "ontology_link",
    "audit_log",
    "learned_action",
    "ontology_embedding",
    "t2_cache",
    "t2_cache_default",
    "state_kv",
    "t1_pattern_library",
    "forecast_episode",
    "forecast_publication_outbox",
    "case_history",
    "case_history_revision",
    "case_history_chunk",
    "case_history_migration_state",
    "conversation_image",
}


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _alembic(*args: str) -> None:
    """Run ``python -m alembic <args...>`` from the repo root."""
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _connect(url: str):  # noqa: ANN202 - helper wraps psycopg lazily
    import psycopg  # local import so the offline test file has no psycopg dependency

    # Alembic accepts SQLAlchemy-style URLs; psycopg wants the plain scheme.
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(plain)


def test_upgrade_head_creates_every_table() -> None:
    url = _requires_live_db()
    _alembic("upgrade", "head")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
        tables = {row[0] for row in cur.fetchall()}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables after upgrade head: {sorted(missing)}"


def test_upgrade_head_installs_pgvector_extension() -> None:
    url = _requires_live_db()
    _alembic("upgrade", "head")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
        found = cur.fetchone()
    assert found is not None, "pgvector extension is not installed"


def test_upgrade_head_creates_hnsw_index_on_embeddings() -> None:
    url = _requires_live_db()
    _alembic("upgrade", "head")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE tablename = 'ontology_embedding'
              AND indexdef ILIKE '%USING hnsw%';
        """)
        rows = cur.fetchall()
    assert rows, "no HNSW index found on ontology_embedding"


def test_downgrade_base_removes_ontology_tables() -> None:
    url = _requires_live_db()
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
        tables = {row[0] for row in cur.fetchall()}
    leftovers = tables & (EXPECTED_TABLES - {"alembic_version"})
    assert not leftovers, f"tables still present after downgrade: {sorted(leftovers)}"

    # Restore head so subsequent tests see the full schema.
    _alembic("upgrade", "head")


def test_ontology_seed_populates_object_and_link_types() -> None:
    """20260705_0003 seeds the 4 ObjectTypes + 6 P1-scope LinkTypes so
    `ontology_resource` / `ontology_link` inserts do not fail on FK."""
    url = _requires_live_db()
    _alembic("upgrade", "head")

    expected_objects = {"Resource", "Rule", "Signal", "Finding"}
    expected_links = {
        "contains",
        "attached_to",
        "depends_on",
        "resource_of",
        "precedes",
        "follows",
    }

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM ontology_object_type;")
        seen_objects = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT name FROM ontology_link_type;")
        seen_links = {row[0] for row in cur.fetchall()}

    missing_objects = expected_objects - seen_objects
    missing_links = expected_links - seen_links
    assert not missing_objects, f"missing ontology_object_type rows: {sorted(missing_objects)}"
    assert not missing_links, f"missing ontology_link_type rows: {sorted(missing_links)}"


def test_ontology_seed_is_idempotent_across_migrations() -> None:
    """Re-running upgrade after downgrade+upgrade keeps exactly the seeded row
    counts (no dup insert, no cascade wipe of user-authored additions)."""
    url = _requires_live_db()
    _alembic("upgrade", "head")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ontology_object_type;")
        (baseline_objects,) = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM ontology_link_type;")
        (baseline_links,) = cur.fetchone()

    _alembic("downgrade", "-1")
    _alembic("upgrade", "head")

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ontology_object_type;")
        (after_objects,) = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM ontology_link_type;")
        (after_links,) = cur.fetchone()

    assert after_objects == baseline_objects, "ontology_object_type row count drifted"
    assert after_links == baseline_links, "ontology_link_type row count drifted"


def test_direction_migration_preserves_unrelated_graph_and_release_pins() -> None:
    url = _requires_live_db()
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.alembic_version')")
        version_table = cur.fetchone()[0]
        if version_table is None:
            current_revision = None
        else:
            cur.execute("SELECT version_num FROM alembic_version")
            current_revision = cur.fetchone()[0]
    if current_revision is None:
        _alembic("upgrade", "20260806_0077")
    elif current_revision != "20260806_0077":
        _alembic("downgrade", "20260806_0077")
    digest = f"sha256:{'a' * 64}"
    previous_digest = "sha256:dd90ae7025bb0472cc091c23e8ed763f7d2ff94a109daf0295a60bb732f33037"
    object_rows = (
        ("migration-parent", {"id": "migration-parent", "type": "resource.group"}),
        (
            "migration-child",
            {
                "id": "migration-child",
                "type": "compute.vm",
                "parent_id": "migration-parent",
            },
        ),
        ("migration-foreign-a", {"id": "migration-foreign-a", "type": "example.a"}),
        ("migration-foreign-b", {"id": "migration-foreign-b", "type": "example.b"}),
        ("migration-vm", {"id": "migration-vm", "type": "compute.vm"}),
        ("migration-nic", {"id": "migration-nic", "type": "network.interface"}),
        ("migration-legacy", {"id": "migration-legacy", "type": "example.legacy"}),
    )
    link_rows = (
        ("contains", "migration-child", "migration-parent"),
        ("contains", "migration-parent", "migration-child"),
        ("contains", "migration-foreign-a", "migration-foreign-b"),
        ("attached_to", "migration-vm", "migration-nic"),
        ("attached_to", "migration-nic", "migration-vm"),
        ("depends_on", "migration-foreign-a", "migration-foreign-b"),
        ("depends_on", "migration-legacy", "migration-foreign-a"),
        ("contains", "migration-legacy", "migration-parent"),
    )
    object_ids = tuple(row[0] for row in object_rows)
    try:
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ontology_link WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                (list(object_ids), list(object_ids)),
            )
            cur.execute("DELETE FROM ontology_resource WHERE id = ANY(%s)", (list(object_ids),))
            cur.executemany(
                "INSERT INTO ontology_resource "
                "(id, object_type, properties, revision, type_version, catalog_digest) "
                "VALUES (%s, 'Resource', %s::jsonb, 1, '1.0.0', %s)",
                (
                    (object_id, json.dumps(properties, sort_keys=True), digest)
                    for object_id, properties in object_rows
                ),
            )
            cur.executemany(
                "INSERT INTO ontology_link "
                "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                "VALUES (%s, %s, %s, '{}'::jsonb, '1.0.0', %s)",
                ((*row, digest) for row in link_rows),
            )
            cur.execute(
                "UPDATE ontology_resource SET catalog_digest = %s WHERE id = 'migration-legacy'",
                (previous_digest,),
            )
            cur.execute(
                "UPDATE ontology_link SET catalog_digest = %s WHERE from_id = 'migration-legacy'",
                (previous_digest,),
            )
            cur.execute(
                "UPDATE ontology_link SET type_version = '2.0.0' "
                "WHERE link_type = 'contains' "
                "AND from_id IN ('migration-parent', 'migration-foreign-a')"
            )
            cur.execute(
                "UPDATE ontology_link SET type_version = NULL, catalog_digest = NULL "
                "WHERE link_type = 'contains' AND from_id = 'migration-legacy'"
            )

        _alembic("upgrade", "head")

        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT link_type, from_id, to_id, type_version, catalog_digest "
                "FROM ontology_link WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                (list(object_ids), list(object_ids)),
            )
            retained = set(cur.fetchall())
            cur.execute(
                "SELECT id, type_version, catalog_digest FROM ontology_resource WHERE id = ANY(%s)",
                (list(object_ids),),
            )
            retained_objects = set(cur.fetchall())
            cur.execute(
                "SELECT version, cardinality FROM ontology_link_type WHERE name = 'contains'"
            )
            contains_declaration = cur.fetchone()
            cur.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'ontology_link'::regclass "
                "AND conname = 'ontology_link_contains_version_direction'"
            )
            contains_guard = cur.fetchone()

        assert retained == {
            ("contains", "migration-parent", "migration-child", "2.0.0", digest),
            ("contains", "migration-foreign-a", "migration-foreign-b", "2.0.0", digest),
            ("attached_to", "migration-nic", "migration-vm", "1.0.0", digest),
            ("depends_on", "migration-foreign-a", "migration-foreign-b", "1.0.0", digest),
            ("depends_on", "migration-legacy", "migration-foreign-a", None, None),
        }
        expected_objects = {
            (object_id, "1.0.0", digest)
            for object_id in object_ids
            if object_id != "migration-legacy"
        }
        expected_objects.add(("migration-legacy", None, None))
        assert retained_objects == expected_objects
        assert contains_declaration == ("2.0.0", "one_to_many")
        assert contains_guard == ("ontology_link_contains_version_direction",)
        with _connect(url) as conn, conn.cursor() as cur:
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="ontology_link_contains_version_direction",
            ):
                cur.execute(
                    "INSERT INTO ontology_link "
                    "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                    "VALUES ('contains', 'migration-child', 'migration-parent', "
                    "'{}'::jsonb, '1.0.0', %s)",
                    (digest,),
                )
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ontology_link "
                "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                "VALUES ('contains', 'migration-legacy', 'migration-parent', "
                "'{}'::jsonb, '2.1.0', %s)",
                (digest,),
            )
    finally:
        _alembic("upgrade", "head")
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ontology_link WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                (list(object_ids), list(object_ids)),
            )
            cur.execute("DELETE FROM ontology_resource WHERE id = ANY(%s)", (list(object_ids),))


def test_direction_guard_repairs_database_already_stamped_at_0078() -> None:
    url = _requires_live_db()
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.alembic_version')")
        version_table = cur.fetchone()[0]
        if version_table is None:
            current_revision = None
        else:
            cur.execute("SELECT version_num FROM alembic_version")
            current_revision = cur.fetchone()[0]
    if current_revision is None:
        _alembic("upgrade", "20260806_0077")
    elif current_revision != "20260806_0077":
        _alembic("downgrade", "20260806_0077")
    _alembic("stamp", "20260808_0078")
    digest = f"sha256:{'b' * 64}"
    object_ids = ("migration-existing-parent", "migration-existing-child")
    try:
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ontology_link_type SET version = '2.0.0', "
                "cardinality = 'one_to_many' WHERE name = 'contains'"
            )
            cur.executemany(
                "INSERT INTO ontology_resource "
                "(id, object_type, properties, revision, type_version, catalog_digest) "
                "VALUES (%s, 'Resource', %s::jsonb, 1, '1.0.0', %s)",
                (
                    (
                        object_id,
                        json.dumps({"id": object_id, "type": "example.resource"}),
                        digest,
                    )
                    for object_id in object_ids
                ),
            )
            cur.execute(
                "INSERT INTO ontology_link "
                "(link_type, from_id, to_id, properties, type_version, catalog_digest) "
                "VALUES ('contains', %s, %s, '{}'::jsonb, '1.0.0', %s)",
                (object_ids[1], object_ids[0], digest),
            )

        _alembic("upgrade", "head")

        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM ontology_link "
                "WHERE from_id = %s AND link_type = 'contains' AND to_id = %s",
                (object_ids[1], object_ids[0]),
            )
            assert cur.fetchone() == (0,)
            cur.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'ontology_link'::regclass "
                "AND conname = 'ontology_link_contains_version_direction'"
            )
            assert cur.fetchone() == ("ontology_link_contains_version_direction",)
    finally:
        _alembic("upgrade", "head")
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ontology_link WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                (list(object_ids), list(object_ids)),
            )
            cur.execute("DELETE FROM ontology_resource WHERE id = ANY(%s)", (list(object_ids),))
