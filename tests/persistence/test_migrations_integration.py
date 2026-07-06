"""Integration test — runs ``alembic upgrade head`` against a live Postgres.

Skipped unless ``AIOPSPILOT_DATABASE_URL`` is set. The docker-compose dev
stack (``make dev-up``) exposes the URL as
``postgresql+psycopg://aiopspilot:devonly@localhost:5432/aiopspilot``.

The test:

1. Runs ``alembic upgrade head`` against the live DB.
2. Verifies every declared table exists.
3. Verifies the pgvector extension is installed.
4. Verifies the HNSW index on ``ontology_embedding`` is present.
5. Downgrades back to ``base`` and asserts tables are gone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
}


def _requires_live_db() -> str:
    url = os.environ.get("AIOPSPILOT_DATABASE_URL")
    if not url:
        pytest.skip("AIOPSPILOT_DATABASE_URL is unset")
    return url


def _alembic(*args: str) -> None:
    """Run ``python -m alembic <args...>`` from the repo root."""
    result = subprocess.run(  # noqa: S603 — controlled subprocess
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _connect(url: str):  # noqa: ANN202 — helper wraps psycopg lazily
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
