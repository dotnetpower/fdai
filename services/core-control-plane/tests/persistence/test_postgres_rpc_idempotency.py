"""PostgreSQL durable RPC idempotency claim tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fdai.core.rpc import RpcResponse
from fdai.delivery.persistence.postgres_rpc_idempotency import (
    PostgresRpcIdempotencyStore,
    PostgresRpcIdempotencyStoreConfig,
    RpcClaimConflictError,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_config_and_key_bounds() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresRpcIdempotencyStoreConfig(dsn="")
    store = PostgresRpcIdempotencyStore(
        config=PostgresRpcIdempotencyStoreConfig(dsn="postgresql://example")
    )
    with pytest.raises(ValueError, match="bounded"):
        asyncio.run(store.claim(""))


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_claim_and_completed_response_survive_restart() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    key = f"workflow.request:{uuid.uuid4().hex}"
    config = PostgresRpcIdempotencyStoreConfig(dsn=dsn)
    store = PostgresRpcIdempotencyStore(config=config)
    assert await store.claim(key) is True
    assert await store.claim(key) is False
    response = RpcResponse(
        request_id="request-1",
        ok=True,
        result={"status": "submitted"},
    )
    await store.complete(key, response)
    with pytest.raises(RpcClaimConflictError):
        await store.complete(key, response)

    restarted = PostgresRpcIdempotencyStore(config=config)
    assert await restarted.get(key) == response
