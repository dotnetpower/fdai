"""Container Apps Job entry point for verified rule collection evidence."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from typing import Any

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.rule_catalog.pipeline.collect import CollectorSuccessReceipt
from fdai.rule_catalog.pipeline.watcher_cli import main as watcher_main
from fdai.shared.providers.state_store import StateStore

_SUCCESS_STATE_PREFIX = "runtime:collector-success:"


async def record_success_receipts(
    store: StateStore,
    summary: Mapping[str, Any],
) -> int:
    """Persist each validated receipt and its audit row exactly once."""
    entries = summary.get("entries")
    if not isinstance(entries, list):
        raise ValueError("collector watcher summary MUST contain entries")
    recorded = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("collect_exit_code") != 0:
            continue
        collect = entry.get("collect")
        if not isinstance(collect, dict):
            continue
        raw_receipt = collect.get("success_receipt")
        if raw_receipt is None:
            continue
        if not isinstance(raw_receipt, dict):
            raise ValueError("collector success receipt MUST be an object")
        receipt = CollectorSuccessReceipt.from_mapping(raw_receipt)
        canonical = json.dumps(
            receipt.to_mapping(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        idempotency_key = f"rule-collector-success:{digest}"
        created = await store.write_state_with_audit_if_absent(
            f"{_SUCCESS_STATE_PREFIX}{receipt.source_id}:{digest}",
            receipt.to_mapping(),
            {
                "kind": "rule_collector.success",
                "event_id": digest,
                "correlation_id": None,
                "tier": "t0",
                "decision": "succeeded",
                "idempotency_key": idempotency_key,
                "actor_identity": "runtime.rule-collector",
                "timestamp": receipt.verified_at.isoformat(),
                "mode": "shadow",
                "rollback_reference": None,
                "source_id": receipt.source_id,
                "resolved_revision": receipt.resolved_revision,
                "content_sha256": receipt.content_sha256,
                "license": receipt.license,
                "redistribution": receipt.redistribution,
                "verified_rules": receipt.verified_rules,
            },
        )
        recorded += int(created)
    return recorded


def main(
    argv: Sequence[str] | None = None,
    *,
    store: StateStore | None = None,
) -> int:
    """Run the verified watcher and durably record every successful source."""
    arguments = list(argv if argv is not None else sys.argv[1:])
    if "--verify" not in arguments:
        arguments.append("--verify")
    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = watcher_main(arguments)
    raw_summary = captured.getvalue()
    try:
        summary = json.loads(raw_summary)
    except json.JSONDecodeError:
        print(raw_summary, end="")
        return exit_code or 2
    if exit_code != 0:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return exit_code
    try:
        state_store = store or _store_from_environment()
        summary["recorded_success_receipts"] = asyncio.run(
            record_success_receipts(state_store, summary)
        )
    except Exception as exc:  # noqa: BLE001 - never expose provider details from a batch job
        print(
            f"error: collector success persistence failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _store_from_environment() -> StateStore:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN is required for collector success evidence")
    return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["main", "record_success_receipts"]
