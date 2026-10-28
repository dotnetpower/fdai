"""Run the initial generation's independent observer before scheduled promotion resumes."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync import _RUN_LOCK_ID as INVENTORY_RUN_LOCK_ID
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)


@asynccontextmanager
async def initial_context(
    config: InventoryJobConfig, timeout_ms: int, initial: bool
) -> AsyncIterator[tuple[AsyncExitStack, PostgresAdvisoryResourceLock | None]]:
    """Hold initial promotion through observation; recurring runs lock in the coordinator."""
    async with AsyncExitStack() as stack:
        lock = PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(dsn=config.dsn, lock_timeout_ms=timeout_ms)
        )
        if initial:
            await stack.enter_async_context(lock.acquire(INVENTORY_RUN_LOCK_ID))
        yield stack, None if initial else lock


async def retain_initial_inventory_closure(config: InventoryJobConfig) -> None:
    """Keep credential values in the child environment and bound observer lifetime."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "fdai.delivery.inventory_closure_cli",
        "--retain-only",
        env={**os.environ, "FDAI_INVENTORY_DSN": config.dsn},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(30):
            return_code = await process.wait()
    except (asyncio.CancelledError, TimeoutError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if return_code != 0:
        raise RuntimeError("initial inventory independent closure retention failed")
