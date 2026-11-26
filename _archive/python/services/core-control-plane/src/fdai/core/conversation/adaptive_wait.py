"""Cancel and drain a single bounded adaptive model or evidence operation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


async def await_adaptive_call[Result](
    operation: Awaitable[Result],
    *,
    timeout: float,
    cancelled: asyncio.Event | None,
) -> Result:
    """Honor caller cancellation while ensuring no child operation outlives the wait."""
    if cancelled is None:
        return await asyncio.wait_for(operation, timeout=timeout)
    work = asyncio.ensure_future(operation)
    cancellation = asyncio.create_task(cancelled.wait())
    tasks = (work, cancellation)
    try:
        done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if cancellation in done or cancelled.is_set():
            raise asyncio.CancelledError
        if work not in done:
            raise TimeoutError
        return work.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
