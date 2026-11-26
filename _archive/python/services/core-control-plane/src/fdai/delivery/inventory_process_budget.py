"""Hard address-space ceiling for the dedicated Linux inventory job process."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

_MIB = 1024 * 1024


def apply_inventory_memory_limit() -> int:
    """Limit the dedicated process, never increase an existing OS limit or touch a peer.

    Address space bounds Python, native buffers and mapped memory across all collection,
    enrichment and publication stages. Database/server memory has a separate owner.
    """
    configured = os.environ.get("FDAI_INVENTORY_MEMORY_LIMIT_MIB", "2048")
    if not configured.isascii() or not configured.isdecimal() or not 256 <= int(configured) <= 4096:
        raise ValueError("inventory process memory limit must be between 256 and 4096 MiB")
    if sys.platform != "linux":
        raise RuntimeError("inventory process memory enforcement requires Linux")
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = min(
        [int(configured) * _MIB]
        + [limit for limit in (soft, hard) if limit != resource.RLIM_INFINITY]
    )
    address_space = int(
        Path("/proc/self/statm").read_text(encoding="ascii").split()[0]
    ) * os.sysconf("SC_PAGE_SIZE")
    if address_space + 64 * _MIB > ceiling:
        raise RuntimeError("inventory process has insufficient memory headroom before collection")
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
    return ceiling


def run_inventory_process(operation: Callable[[], Coroutine[Any, Any, None]]) -> None:
    apply_inventory_memory_limit()
    asyncio.run(operation())
