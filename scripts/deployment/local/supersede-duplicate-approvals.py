#!/usr/bin/env python3
"""Supersede duplicate pending approvals in the loopback development database.

The default run only reports what would change. ``--apply`` links each older duplicate to the
newest open request of the same subject, keeps every record, and writes one audit entry per
change. Only loopback host and host-address entries on port 5432 for database ``fdai`` are
accepted, and no connection value is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
from datetime import UTC, datetime

from fdai.core.hil_resume.subject_cleanup import (
    apply_duplicate_cleanup,
    plan_duplicate_cleanup,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"


def _all_loopback_hostaddrs(raw: str) -> bool:
    """Return whether every comma-separated libpq host address is a loopback IP."""
    for address in raw.split(","):
        try:
            if not ipaddress.ip_address(address.strip()).is_loopback:
                return False
        except ValueError:
            return False
    return True


def _dsn() -> str:
    raw = os.environ.get(_DSN_ENV, "").strip()
    if not raw:
        raise SystemExit(f"{_DSN_ENV} is not set; source .fdai/local-runtime.env first")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    info = conninfo_to_dict(dsn)
    if (
        str(info.get("host") or "") not in _LOOPBACK_HOSTS
        or (bool(info.get("hostaddr")) and not _all_loopback_hostaddrs(str(info["hostaddr"])))
        or str(info.get("port") or "5432") != "5432"
        or str(info.get("dbname") or "") != "fdai"
    ):
        raise SystemExit("approval cleanup requires loopback port 5432 and database fdai")
    return dsn


async def _run(*, apply: bool) -> dict[str, object]:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_dsn()))
    try:
        plan = await plan_duplicate_cleanup(store)
        report: dict[str, object] = {
            "mode": "apply" if apply else "dry-run",
            "open_requests": plan.open_total,
            "subjects": plan.subject_total,
            "unrecognized": plan.unrecognized,
            "subjects_with_duplicates": len(plan.groups),
            "to_supersede": plan.superseded_total,
        }
        if apply:
            result = await apply_duplicate_cleanup(store, plan, now=datetime.now(UTC))
            report.update(
                superseded=result.superseded,
                skipped_changed=result.skipped_changed,
                subjects_seeded=result.subjects_seeded,
            )
        return report
    finally:
        await store.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes; without it the run only reports them",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(apply=args.apply)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
