"""Bounded freshness renewal for the Release Hub development export."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from fdai_release_hub.store import ReleaseStore

logger = logging.getLogger(__name__)


async def run_renewal(
    store: ReleaseStore,
    *,
    check_seconds: int,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Check on a fixed interval and renew only when the validity is nearly spent."""

    while True:
        try:
            renewed = await run_in_threadpool(store.renew_if_due)
            if renewed:
                logger.info("release_catalog_freshness_renewed")
        except Exception as error:  # noqa: BLE001 - one failed check must not stop future checks
            logger.error("release_catalog_renewal_failed category=%s", type(error).__name__)
        await sleep(check_seconds)
