"""Loopback PostgreSQL proof of ``read_state_page`` dotted field-path filters.

Skipped unless ``FDAI_DATABASE_URL`` points to a dedicated validation database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

from tests.providers.state_store_field_path_cases import assert_field_path_semantics

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]


def postgres_store() -> PostgresStateStore:
    """Return a migrated store for the dedicated validation database, or skip."""

    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))


@pytest.mark.asyncio
async def test_postgres_nested_filter_matches_booleans_paths_and_escaping() -> None:
    await assert_field_path_semantics(postgres_store(), f"field_path%{uuid.uuid4().hex}:")


@pytest.mark.asyncio
async def test_postgres_single_identifier_filter_is_unchanged() -> None:
    store = postgres_store()
    prefix = f"field-top-{uuid.uuid4().hex}:"
    await store.write_state(f"{prefix}a", {"source_confirmed": True})
    await store.write_state(f"{prefix}b", {"source_confirmed": False})

    rows, total = await store.read_state_page(
        prefix, limit=10, field="source_confirmed", value="true"
    )
    assert total == 1 and rows[0] == {"source_confirmed": True}
    with pytest.raises(ValueError, match="ASCII identifier"):
        await store.read_state_page(prefix, limit=10, field="kind;drop", value="x")
