#!/usr/bin/env python3
"""Export one non-secret WARA workload binding from current PostgreSQL topology."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_DATABASE_ENV = "FDAI_FRAMEWORK_ASSESSMENT_DSN"
_WORKLOAD_ENV = "FDAI_WARA_WORKLOAD_IDS_JSON"
_QUERY = (
    "SELECT DISTINCT resource.id "
    "FROM ontology_resource AS resource "
    "WHERE resource.object_type='Workload' "
    "AND EXISTS ("
    "SELECT 1 FROM ontology_link AS link "
    "WHERE link.from_id=resource.id "
    "AND link.link_type='workload_runs_on'"
    ") "
    "ORDER BY resource.id LIMIT 2"
)


def select_wara_workload_id(rows: Sequence[Mapping[str, object]]) -> str:
    """Select one topology-bound workload without exposing candidate identifiers."""

    if not rows:
        raise ValueError("expected exactly one topology-bound WARA workload; found 0")
    if len(rows) != 1:
        raise ValueError("expected exactly one topology-bound WARA workload; found at least 2")
    workload_id = rows[0].get("id")
    if not isinstance(workload_id, str) or not workload_id.strip():
        raise ValueError("the topology-bound WARA workload id is invalid")
    if workload_id != workload_id.strip() or "\n" in workload_id or "\r" in workload_id:
        raise ValueError("the topology-bound WARA workload id is invalid")
    return workload_id


def discover_wara_workload_id(dsn: str) -> str:
    """Read one candidate in a bounded, read-only PostgreSQL transaction."""

    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            ("15000",),
        )
        rows = connection.execute(_QUERY).fetchall()
    return select_wara_workload_id(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-env", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get(_DATABASE_ENV, "").strip()
    if not dsn:
        raise ValueError(f"{_DATABASE_ENV} is required")
    workload_id = discover_wara_workload_id(dsn)
    encoded = json.dumps([workload_id], ensure_ascii=True, separators=(",", ":"))
    with args.github_env.open("a", encoding="utf-8") as stream:
        stream.write(f"{_WORKLOAD_ENV}={encoded}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
