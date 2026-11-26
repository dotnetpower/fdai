#!/usr/bin/env python3
"""Regenerate offline mechanics receipts from the canonical executable compatibility gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_service_contracts import generate_upgrade_receipts, load_json_object, validate_manifest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/service-contracts"
TARGET = PACKAGE / "tests/fixtures/services/upgrade-receipts.json"


def normalize_fixture_metadata(
    receipts: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Preserve historical offline identities by service/direction, never input position.

    Only synthetic fixture IDs and clocks are replaced; checks, versions, matrix
    digests and peer evidence are copied unchanged. Unknown or incomplete transitions
    and non-focused evidence cannot be normalized into an apparently valid fixture.
    """
    services = (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    )
    order = tuple(
        (service, direction) for service in services for direction in ("migration", "rollback")
    )
    if any(receipt.get("proof_kind") != "focused" for receipt in receipts):
        raise ValueError("fixture generation cannot produce live evidence")
    by_identity = {(row["service_id"], row["direction"]): row for row in receipts}
    if len(receipts) != len(order) or set(by_identity) != set(order):
        raise ValueError("fixture transitions must cover each canonical service and direction once")
    normalized: list[dict[str, Any]] = []
    for index, identity in enumerate(order):
        receipt = dict(by_identity[identity])
        at = datetime(2026, 8, 8, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
        receipt["receipt_id"] = f"00000000-0000-0000-0000-{201 + index:012d}"
        receipt["started_at"] = at.isoformat().replace("+00:00", "Z")
        receipt["completed_at"] = (at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        normalized.append(receipt)
    return tuple(normalized)


def main() -> int:
    """Refresh only focused fixtures; never rewrite a live receipt or its certified matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "scripts/quality/architecture/check-service-compatibility.py"
    spec = importlib.util.spec_from_file_location("service_compatibility_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("service compatibility gate is unavailable")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    manifest = load_json_object(PACKAGE / "src/fdai_service_contracts/compatibility-manifest.json")
    validate_manifest(manifest)
    checker._validate_wire_payloads(checker._contract_map(manifest))
    checker._validate_delivery_traces()
    checks = checker._upgrade_checks(manifest)
    if not all(checks.values()):
        raise RuntimeError("service compatibility mechanics checks failed")
    receipts = normalize_fixture_metadata(generate_upgrade_receipts(manifest, checks=checks))
    rendered = json.dumps(receipts, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        return int(not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"service-compatibility-fixtures: focused={len(receipts)} live=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
