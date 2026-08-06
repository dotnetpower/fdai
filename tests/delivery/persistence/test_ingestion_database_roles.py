"""Live PostgreSQL least-privilege checks for independent ingestion roles."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from fdai.delivery.ingestion_gateway.prod import (
    ProdIngestionConfigError,
    _verify_database_role,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _role_dsn(database_url: str, role: str) -> str:
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    separator = "&" if "?" in dsn else "?"
    return f"{dsn}{separator}options=-c%20role%3D{role}"


async def _privilege(dsn: str, role: str, table: str, privilege: str) -> bool:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute(
            "SELECT has_table_privilege(%s, %s, %s) AS allowed",
            (role, table, privilege),
        )
        row = await cursor.fetchone()
    assert row is not None
    return bool(row[0])


@pytest.mark.integration
async def test_live_ingestion_database_roles_are_distinct_and_least_privileged() -> None:
    database_url = os.environ.get("FDAI_DATABASE_URL")
    if not database_url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    upgraded = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upgraded.returncode == 0, upgraded.stderr
    api_role = "fdai_ingestion_api"
    worker_role = "fdai_ingestion_worker"
    api_dsn = _role_dsn(database_url, api_role)
    worker_dsn = _role_dsn(database_url, worker_role)

    async with await psycopg.AsyncConnection.connect(api_dsn) as connection:
        row = await (await connection.execute("SELECT current_user")).fetchone()
        assert row is not None and row[0] == api_role
    async with await psycopg.AsyncConnection.connect(worker_dsn) as connection:
        row = await (await connection.execute("SELECT current_user")).fetchone()
        assert row is not None and row[0] == worker_role

    await _verify_database_role(api_dsn, api_role)
    with pytest.raises(ProdIngestionConfigError, match="effective PostgreSQL role"):
        await _verify_database_role(api_dsn, worker_role)

    assert await _privilege(api_dsn, api_role, "document_upload_session", "INSERT")
    assert await _privilege(api_dsn, api_role, "knowledge_chunk", "SELECT")
    assert not await _privilege(api_dsn, api_role, "knowledge_chunk", "INSERT")
    assert not await _privilege(api_dsn, api_role, "document_worker_claim", "INSERT")
    assert not await _privilege(api_dsn, api_role, "audit_log", "DELETE")

    assert await _privilege(worker_dsn, worker_role, "document_upload_session", "UPDATE")
    assert not await _privilege(worker_dsn, worker_role, "document_upload_session", "INSERT")
    assert await _privilege(worker_dsn, worker_role, "knowledge_chunk", "INSERT")
    assert await _privilege(worker_dsn, worker_role, "document_worker_claim", "INSERT")
    assert not await _privilege(worker_dsn, worker_role, "audit_log", "DELETE")
