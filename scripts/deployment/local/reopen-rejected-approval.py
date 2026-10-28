#!/usr/bin/env python3
"""Reopen one rejected approval subject in the loopback development database.

The default run only reports whether the subject can be reopened. ``--apply`` records one audit
entry naming ``--actor`` so the next proposal for the same subject parks a new linked request.
The rejected request itself is never edited. Only loopback port 5432 database ``fdai`` is
accepted, and no connection value is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

from fdai.core.hil_resume.subject_index import reopen_rejected_subject
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"


def _dsn() -> str:
    raw = os.environ.get(_DSN_ENV, "").strip()
    if not raw:
        raise SystemExit(f"{_DSN_ENV} is not set; source .fdai/local-runtime.env first")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    info = conninfo_to_dict(dsn)
    if (
        str(info.get("host") or "") not in _LOOPBACK_HOSTS
        or str(info.get("port") or "5432") != "5432"
        or str(info.get("dbname") or "") != "fdai"
    ):
        raise SystemExit("approval reopen requires loopback port 5432 and database fdai")
    return dsn


async def _run(*, approval_id: str, actor: str, apply: bool) -> dict[str, object]:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_dsn()))
    try:
        outcome = await reopen_rejected_subject(
            store, approval_id=approval_id, actor=actor, now=datetime.now(UTC), apply=apply
        )
    finally:
        await store.aclose()
    return {"mode": "apply" if apply else "dry-run", "approval_id": approval_id, "outcome": outcome}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-id", required=True, help="the rejected approval to reopen")
    parser.add_argument(
        "--actor", required=True, help="who reopens it; recorded in the audit entry"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the change; without it the run only reports"
    )
    args = parser.parse_args()
    report = asyncio.run(_run(approval_id=args.approval_id, actor=args.actor, apply=args.apply))
    print(json.dumps(report, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
