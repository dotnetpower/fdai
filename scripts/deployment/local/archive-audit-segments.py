#!/usr/bin/env python3
"""Export old audit rows of the loopback development database as verified zstd segments.

Non-destructive: rows are copied to ``.fdai/audit-archive`` and never deleted. Each segment is a
contiguous run of ``audit_log`` rows (JSON lines, Zstandard compressed) whose hash chain is
recomputed before and after writing, anchored to the previous segment, and recorded in
``manifest.jsonl`` with the digests needed to verify it later. The newest 512 rows and every row
younger than ``--older-than-days`` are never exported, so the Saga recovery window stays hot.

Only loopback port 5432 database ``fdai`` is accepted and no connection value is printed.
Removing exported rows from the table needs a chain verifier that accepts a manifest anchor and is
intentionally not part of this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from fdai.rule_catalog.schema.zstd_codec import compress_bytes, decompress_bytes
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash
from psycopg.conninfo import conninfo_to_dict

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DSN_ENV = "FDAI_STATE_STORE_DSN"
_HOT_TAIL_ROWS = 512
_DEFAULT_OUT = Path(".fdai/audit-archive")
_MANIFEST = "manifest.jsonl"
_COLUMNS = (
    "seq",
    "event_id",
    "correlation_id",
    "actor",
    "action_kind",
    "mode",
    "entry",
    "previous_hash",
    "entry_hash",
    "created_at",
)
_SELECT_SQL = (
    "SELECT seq, event_id, correlation_id, actor, action_kind, mode, entry, "
    "previous_hash, entry_hash, created_at FROM audit_log "
    "WHERE seq > %s AND seq <= %s AND created_at < %s ORDER BY seq LIMIT %s"
)
_MAX_SEGMENT_BYTES = 512 * 1024 * 1024
_ZSTD_LEVEL = 10


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
        raise SystemExit("audit archive requires loopback port 5432 and database fdai")
    return dsn


def _row_record(row: tuple[Any, ...]) -> dict[str, Any]:
    record = dict(zip(_COLUMNS, row, strict=True))
    record["event_id"] = str(record["event_id"])
    record["created_at"] = record["created_at"].isoformat()
    return record


def verify_records(records: list[dict[str, Any]], *, anchor: str) -> str:
    """Recompute a contiguous chain from ``anchor`` and return its final entry hash."""
    previous = anchor
    for record in records:
        if record["previous_hash"] != previous:
            raise ValueError(f"audit chain link broken at seq {record['seq']}")
        if record["entry_hash"] != next_hash(previous, record["entry"]):
            raise ValueError(f"audit entry hash mismatch at seq {record['seq']}")
        previous = record["entry_hash"]
    return previous


def _encode(records: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _decode(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]


def read_manifest(out: Path) -> list[dict[str, Any]]:
    path = out / _MANIFEST
    if not path.is_file():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    anchor = GENESIS_HASH
    for entry in entries:
        if entry["first_previous_hash"] != anchor:
            raise SystemExit("audit archive manifest is not a contiguous chain")
        anchor = entry["last_entry_hash"]
    return entries


def write_segment(out: Path, records: list[dict[str, Any]], *, anchor: str) -> dict[str, Any]:
    """Write, re-read, and verify one segment; return its manifest entry."""
    last_hash = verify_records(records, anchor=anchor)
    envelope = compress_bytes(_encode(records), level=_ZSTD_LEVEL)
    name = f"segment-{records[0]['seq']:012d}-{records[-1]['seq']:012d}.jsonl.zst"
    target, partial = out / name, out / (name + ".partial")
    with partial.open("wb") as handle:
        handle.write(envelope.compressed_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    partial.chmod(0o600)
    restored = _decode(
        decompress_bytes(
            partial.read_bytes(),
            max_output_size=_MAX_SEGMENT_BYTES,
            expected_uncompressed_sha256=envelope.uncompressed_sha256,
        )
    )
    if verify_records(restored, anchor=anchor) != last_hash or restored != json.loads(
        json.dumps(records)
    ):
        raise ValueError("archived segment does not restore to the exported rows")
    partial.replace(target)
    return {
        "segment": name,
        "first_seq": records[0]["seq"],
        "last_seq": records[-1]["seq"],
        "rows": len(records),
        "first_previous_hash": anchor,
        "last_entry_hash": last_hash,
        "uncompressed_sha256": envelope.uncompressed_sha256,
        "compressed_sha256": "sha256:" + hashlib.sha256(envelope.compressed_bytes).hexdigest(),
        "uncompressed_size": envelope.uncompressed_size,
        "compressed_size": envelope.compressed_size,
    }


def archive(
    dsn: str, out: Path, *, older_than: timedelta, segment_rows: int, max_segments: int
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = read_manifest(out)
    anchor = manifest[-1]["last_entry_hash"] if manifest else GENESIS_HASH
    after = manifest[-1]["last_seq"] if manifest else 0
    cutoff = datetime.now(tz=UTC) - older_than
    written: list[dict[str, Any]] = []
    with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=120000") as db:
        db.execute("SET default_transaction_read_only = on")
        head = db.execute("SELECT COALESCE(max(seq), 0) FROM audit_log").fetchone()
        hot_from = (int(head[0]) if head else 0) - _HOT_TAIL_ROWS
        for _ in range(max_segments):
            rows = db.execute(_SELECT_SQL, (after, hot_from, cutoff, segment_rows)).fetchall()
            if not rows:
                break
            records = [_row_record(row) for row in rows]
            if after == 0 and records[0]["previous_hash"] != GENESIS_HASH:
                raise SystemExit("audit_log does not start at the chain genesis; nothing archived")
            entry = write_segment(out, records, anchor=anchor)
            with (out / _MANIFEST).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
            (out / _MANIFEST).chmod(0o600)
            written.append(entry)
            anchor, after = entry["last_entry_hash"], entry["last_seq"]
    raw = sum(item["uncompressed_size"] for item in written)
    packed = sum(item["compressed_size"] for item in written)
    return {
        "segments_written": len(written),
        "rows": sum(item["rows"] for item in written),
        "uncompressed_bytes": raw,
        "compressed_bytes": packed,
        "ratio": round(raw / packed, 2) if packed else None,
        "archived_through_seq": after,
        "deleted_rows": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--older-than-days", type=float, default=2.0)
    parser.add_argument("--segment-rows", type=int, default=20_000)
    parser.add_argument("--max-segments", type=int, default=50)
    args = parser.parse_args()
    if args.older_than_days < 0 or args.segment_rows < 1 or args.max_segments < 1:
        parser.error("bounds MUST be positive")
    report = archive(
        _dsn(),
        args.out,
        older_than=timedelta(days=args.older_than_days),
        segment_rows=args.segment_rows,
        max_segments=args.max_segments,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
