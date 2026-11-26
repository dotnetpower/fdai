#!/usr/bin/env python3
"""Dry-run or apply a reviewed Saga audit migration using the service environment."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import psycopg
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_saga_migration import migrate_saga_audit_chain


async def _run(arguments: argparse.Namespace) -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL")
    if not dsn:
        raise ValueError("FDAI_DATABASE_URL is required from the Core service environment")
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            statement_timeout_ms=5_000,
        )
    )
    try:
        plan = await migrate_saga_audit_chain(
            store,
            expected_plan_digest=arguments.apply_plan,
            legacy_writers_quiesced=arguments.legacy_writers_quiesced,
            preserve_detached_histories=arguments.preserve_detached_histories,
        )
        print(
            json.dumps(
                {
                    "status": "applied" if arguments.apply_plan else "dry_run",
                    "plan_digest": plan.plan_digest,
                    **plan.summary(),
                },
                sort_keys=True,
            )
        )
    finally:
        await store.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-plan", help="Exact plan_digest from a reviewed dry-run")
    parser.add_argument("--legacy-writers-quiesced", action="store_true")
    parser.add_argument("--preserve-detached-histories", action="store_true")
    try:
        asyncio.run(_run(parser.parse_args()))
    except (RuntimeError, ValueError, psycopg.Error, TimeoutError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_kind": type(exc).__name__,
                    "reason": (
                        "Migration failed. Verify the checkpoint and receipt before continuing. "
                        "Check the service environment, legacy writer quiescence, complete "
                        "history integrity, and the exact reviewed plan digest."
                    ),
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
