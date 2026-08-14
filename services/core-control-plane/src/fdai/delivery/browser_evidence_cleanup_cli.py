"""One-shot bounded cleanup entry point for expired browser evidence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TextIO

from fdai.delivery.persistence.postgres_browser_evidence import (
    PostgresBrowserEvidenceArtifactStore,
    PostgresBrowserEvidenceArtifactStoreConfig,
)

_LOGGER = logging.getLogger(__name__)
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class BrowserEvidenceCleanupConfig:
    """Validated server-owned settings for one retention cleanup attempt."""

    dsn: str
    limit: int = _DEFAULT_LIMIT

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> BrowserEvidenceCleanupConfig:
        source = env if env is not None else os.environ
        dsn = source.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise ValueError("FDAI_DATABASE_URL MUST NOT be empty")
        raw_limit = source.get("FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT", str(_DEFAULT_LIMIT))
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise ValueError("FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT MUST be an integer") from exc
        if not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT MUST be in [1, 500]")
        return cls(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            limit=limit,
        )


PurgeExpired = Callable[
    [BrowserEvidenceCleanupConfig, datetime],
    Awaitable[tuple[str, ...]],
]


async def _purge_expired(
    config: BrowserEvidenceCleanupConfig,
    now: datetime,
) -> tuple[str, ...]:
    store = PostgresBrowserEvidenceArtifactStore(
        config=PostgresBrowserEvidenceArtifactStoreConfig(dsn=config.dsn)
    )
    return await store.purge_expired(now=now, limit=config.limit)


async def run_once(
    *,
    env: Mapping[str, str] | None = None,
    purge: PurgeExpired = _purge_expired,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    output: TextIO,
) -> int:
    """Purge one bounded batch and emit no artifact or database identifiers."""

    config = BrowserEvidenceCleanupConfig.from_env(env)
    now = clock()
    if now.tzinfo is None:
        raise RuntimeError("browser evidence cleanup clock MUST include timezone")
    now = now.astimezone(UTC)
    purged = await purge(config, now)
    if len(purged) > config.limit:
        raise RuntimeError("browser evidence cleanup exceeded its configured limit")
    output.write(
        json.dumps(
            {"purged_count": len(purged), "status": "completed"},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    output.flush()
    return 0


def main() -> int:
    """Run one cleanup and map configuration or database failures to exit code 3."""

    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(run_once(output=sys.stdout))
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits one fixed job result
        _LOGGER.error(
            "browser_evidence_cleanup_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BrowserEvidenceCleanupConfig", "main", "run_once"]
