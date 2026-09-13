#!/usr/bin/env python3
"""Assemble the cross-path safeguard evidence bundle from retained receipts.

The builder is deliberately dumb about semantics and strict about shape. It
refuses duplicate JSON keys, unexpected or missing receipt kinds, non-finite
numbers, and any attempt to overwrite an existing bundle. Judging whether the
assembled evidence is *sufficient* belongs to the verifier, so a bundle that
builds still has to earn its acceptance separately.

This script performs no network call, no deployment, and no effect. It reads
local files and writes exactly one JSON document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT = _ROOT / "config/cross-path-safeguard-evidence.json"

#: Receipt kinds a complete campaign must retain, one per concern.
REQUIRED_RECEIPT_KINDS: frozenset[str] = frozenset(
    {
        "approval",
        "revision_pin",
        "deployment_preflight",
        "matrix_cell",
        "denial_class",
        "observation",
        "rollback",
        "cleanup",
    }
)

#: Fields every receipt carries so the verifier can attribute it.
REQUIRED_RECEIPT_FIELDS: frozenset[str] = frozenset(
    {
        "kind",
        "cell_id",
        "base_revision",
        "recorded_at",
        "synthetic",
        "authority_class",
        "content",
    }
)


class BundleError(RuntimeError):
    """The retained receipts cannot form an honest bundle."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse a JSON object that silently overwrote one of its own keys."""

    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise BundleError(f"duplicate JSON key {key!r} in receipt")
        seen[key] = value
    return seen


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except json.JSONDecodeError as exc:
        raise BundleError(f"{path.name}: invalid JSON: {exc}") from exc


def _reject_non_finite(value: Any, path: str) -> None:
    """Refuse NaN and infinity, which do not round-trip through JSON."""

    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise BundleError(f"{path}: non-finite number is not retainable evidence")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")


def _validate_receipt(receipt: Any, path: Path) -> Mapping[str, Any]:
    if not isinstance(receipt, Mapping):
        raise BundleError(f"{path.name}: receipt MUST be a JSON object")
    missing = REQUIRED_RECEIPT_FIELDS - set(receipt)
    if missing:
        raise BundleError(f"{path.name}: receipt omits {sorted(missing)}")
    unexpected = set(receipt) - REQUIRED_RECEIPT_FIELDS
    if unexpected:
        raise BundleError(f"{path.name}: receipt carries unexpected {sorted(unexpected)}")
    kind = receipt["kind"]
    if kind not in REQUIRED_RECEIPT_KINDS:
        raise BundleError(f"{path.name}: unknown receipt kind {kind!r}")
    if receipt["authority_class"] != "no_authority":
        raise BundleError(f"{path.name}: a retained receipt MUST NOT claim authority")
    _reject_non_finite(receipt, path.name)
    return receipt


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build(
    *,
    receipt_dir: Path,
    output_path: Path,
    campaign_id: str,
    base_revision: str,
) -> Mapping[str, Any]:
    """Assemble one bundle, refusing to overwrite an existing one."""

    if output_path.exists():
        raise BundleError(f"{output_path} already exists; a bundle is written once")
    contract = _load_json(_CONTRACT)
    if not isinstance(contract, Mapping):
        raise BundleError("cross-path safeguard contract MUST be a JSON object")
    receipt_paths = sorted(receipt_dir.glob("*.json"))
    if not receipt_paths:
        raise BundleError(f"no receipts found under {receipt_dir}")

    receipts: list[Mapping[str, Any]] = []
    seen_digests: set[str] = set()
    for path in receipt_paths:
        receipt = _validate_receipt(_load_json(path), path)
        if receipt["base_revision"] != base_revision:
            raise BundleError(
                f"{path.name}: receipt pins {receipt['base_revision']!r}, "
                f"campaign pins {base_revision!r}"
            )
        digest = hashlib.sha256(_canonical(receipt)).hexdigest()
        if digest in seen_digests:
            raise BundleError(f"{path.name}: duplicate receipt content")
        seen_digests.add(digest)
        receipts.append(receipt)

    present = {str(receipt["kind"]) for receipt in receipts}
    missing_kinds = REQUIRED_RECEIPT_KINDS - present
    if missing_kinds:
        raise BundleError(f"bundle omits receipt kinds {sorted(missing_kinds)}")

    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "campaign_id": campaign_id,
        "base_revision": base_revision,
        "contract_digest": hashlib.sha256(_canonical(contract)).hexdigest(),
        "receipts": sorted(receipts, key=lambda item: (str(item["kind"]), str(item["cell_id"]))),
    }
    body["bundle_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return body


def main(argv: Sequence[str] | None = None) -> int:
    """Build one bundle and report its digest."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--base-revision", required=True)
    args = parser.parse_args(argv)

    try:
        bundle = build(
            receipt_dir=args.receipt_dir,
            output_path=args.output,
            campaign_id=args.campaign_id,
            base_revision=args.base_revision,
        )
    except BundleError as exc:
        print(f"cross-path-safeguard-bundle: ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"cross-path-safeguard-bundle: OK {bundle['bundle_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
