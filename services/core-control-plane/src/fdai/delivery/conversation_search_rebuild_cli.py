"""Headless conversation-search projection rebuild entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TextIO

from fdai.delivery.persistence.postgres_conversation_search import PostgresConversationSearch
from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConversationSearchRebuildConfig:
    """Validated server-owned settings for one projection rebuild."""

    dsn: str

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> ConversationSearchRebuildConfig:
        source = env if env is not None else os.environ
        dsn = source.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise ValueError("FDAI_DATABASE_URL MUST NOT be empty")
        return cls(dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1))


RebuildProjection = Callable[
    [ConversationSearchRebuildConfig],
    Awaitable[Mapping[str, int | float]],
]


async def _rebuild_projection(
    config: ConversationSearchRebuildConfig,
) -> Mapping[str, int | float]:
    search = PostgresConversationSearch(config=PostgresUserContextStoreConfig(dsn=config.dsn))
    return await search.rebuild_projection()


async def run_once(
    *,
    env: Mapping[str, str] | None = None,
    rebuild: RebuildProjection = _rebuild_projection,
    output: TextIO,
) -> int:
    """Rebuild once and emit only bounded, machine-readable measurements."""

    metrics = _bounded_metrics(await rebuild(ConversationSearchRebuildConfig.from_env(env)))
    output.write(json.dumps(metrics, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def _bounded_metrics(metrics: Mapping[str, int | float]) -> dict[str, int | float | str]:
    result: dict[str, int | float | str] = {"status": "completed"}
    for key in ("index_rows", "index_bytes", "duration_ms"):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise RuntimeError("conversation search rebuild returned invalid metrics")
        result[key] = value
    return result


def main() -> int:
    """Run one rebuild and map configuration or database failures to exit code 3."""

    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(run_once(output=sys.stdout))
    except Exception as exc:  # noqa: BLE001 - CLI boundary maps failures to a fixed job result
        _LOGGER.error(
            "conversation_search_rebuild_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ConversationSearchRebuildConfig", "main", "run_once"]
