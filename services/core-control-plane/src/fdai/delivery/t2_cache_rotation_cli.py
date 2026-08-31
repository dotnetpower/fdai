"""One-shot service-owned T2 cache partition rotation command."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TextIO

import psycopg

from fdai.delivery.persistence.postgres_t2_cache import (
    PostgresT2Cache,
    PostgresT2CacheConfig,
    T2CacheLifecycleError,
)

_LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", required=True, help="exact active catalog SHA-256 digest")
    parser.add_argument("--rollback", required=True, help="exact rollback catalog SHA-256 digest")
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--cutoff", help="RFC 3339 cutoff; defaults to current UTC time")
    return parser


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--cutoff must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--cutoff must include a timezone")
    return parsed.astimezone(UTC)


async def run(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    output: TextIO,
) -> int:
    """Validate one rotation request, execute it atomically, and print its receipt."""
    args = _parser().parse_args(argv)
    source = env if env is not None else os.environ
    dsn = source.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        raise ValueError("FDAI_DATABASE_URL must be non-empty")
    store = PostgresT2Cache(
        config=PostgresT2CacheConfig(dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1))
    )
    receipt = await store.rotate(
        active_catalog_version=args.active,
        rollback_catalog_version=args.rollback,
        idempotency_key=args.idempotency_key,
        cutoff=_cutoff(args.cutoff),
    )
    output.write(
        json.dumps(
            {
                "dropped_count": len(receipt.dropped_catalog_versions),
                "receipt_digest": receipt.receipt_digest,
                "status": "completed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded rotation command and return a stable failure exit code."""
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(run(tuple(argv or sys.argv[1:]), output=sys.stdout))
    except (ValueError, T2CacheLifecycleError, psycopg.Error) as exc:
        _LOGGER.error(
            "t2_cache_rotation_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
