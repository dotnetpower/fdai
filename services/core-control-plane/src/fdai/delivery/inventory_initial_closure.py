"""Run the initial generation's independent observer before scheduled promotion resumes."""

from __future__ import annotations

import asyncio
import os
import sys

from fdai.delivery.inventory_job_config import InventoryJobConfig


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
