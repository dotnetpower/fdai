"""Read one sanitized forecast operational evidence snapshot."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
)

_DSN_ENV = "FDAI_STATE_STORE_DSN"


class ForecastEvidenceReader(Protocol):
    """Read-only forecast evidence surface used by the maintenance query."""

    async def health_snapshot(self, *, now: datetime) -> Mapping[str, object]: ...


async def query_forecast_evidence(
    *,
    reader: ForecastEvidenceReader,
    observed_at: datetime,
) -> dict[str, object]:
    """Return the sanitized repeatable-read operational snapshot."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("forecast evidence observed_at MUST be timezone-aware")
    snapshot = dict(await reader.health_snapshot(now=observed_at.astimezone(UTC)))
    return {
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "snapshot": snapshot,
    }


def main() -> None:
    """Run one read-only snapshot from a Container Apps execution."""

    if len(sys.argv) != 1:
        raise ValueError("forecast evidence query accepts no arguments")
    dsn = os.environ.get(_DSN_ENV, "").strip()
    if not dsn:
        raise ValueError(f"{_DSN_ENV} MUST NOT be empty")
    result = asyncio.run(
        query_forecast_evidence(
            reader=PostgresForecastEpisodeStore(
                config=PostgresForecastEpisodeStoreConfig(
                    dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
                )
            ),
            observed_at=datetime.now(UTC),
        )
    )
    print("forecast-evidence:" + json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
