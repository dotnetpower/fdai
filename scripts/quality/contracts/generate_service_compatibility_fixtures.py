#!/usr/bin/env python3
"""Regenerate offline mechanics receipts from the canonical executable compatibility gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_service_contracts import generate_upgrade_receipts, load_json_object, validate_manifest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/service-contracts"
TARGET = PACKAGE / "tests/fixtures/services/upgrade-receipts.json"


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
    receipts = generate_upgrade_receipts(manifest, checks=checks)
    if any(receipt.get("proof_kind") != "focused" for receipt in receipts):
        raise RuntimeError("fixture generation cannot produce live evidence")
    # Only offline fixture metadata uses placeholder identities and a fixed clock.
    # Executed checks, peer requirements and the actual matrix digest remain intact.
    for index, receipt in enumerate(receipts):
        at = datetime(2026, 8, 8, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
        receipt["receipt_id"] = f"00000000-0000-0000-0000-{201 + index:012d}"
        receipt["started_at"] = at.isoformat().replace("+00:00", "Z")
        receipt["completed_at"] = (at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    rendered = json.dumps(receipts, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        return int(not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"service-compatibility-fixtures: focused={len(receipts)} live=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
