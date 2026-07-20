"""Rebuild and measure the generated conversation search projection."""

from __future__ import annotations

import asyncio
import json
import os

from fdai.delivery.persistence import (
    PostgresConversationSearch,
    PostgresUserContextStoreConfig,
)


async def _run() -> int:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN is required")
    search = PostgresConversationSearch(config=PostgresUserContextStoreConfig(dsn=dsn))
    print(json.dumps(await search.rebuild_projection(), sort_keys=True))
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
