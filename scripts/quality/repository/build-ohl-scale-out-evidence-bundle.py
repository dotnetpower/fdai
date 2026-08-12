#!/usr/bin/env python3
"""Assemble protected-runner OHL receipts and samples into one evidence bundle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON object key: {key}")
            value[key] = item
        return value

    def reject_non_finite(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(
        path.read_bytes(),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_non_finite,
    )


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be an object")
    return value


def _string_set(value: object, field: str) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} MUST be an array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} MUST contain unique strings")
    result = set(value)
    if len(result) != len(value):
        raise ValueError(f"{field} MUST contain unique strings")
    return result


def build_bundle(
    manifest: object,
    receipts: Sequence[object],
    samples: object,
    *,
    campaign_id: str,
    correlation_id: str,
    target_revision: str,
    started_at: str,
    recurrence_observed_at: str,
) -> dict[str, object]:
    contract = _mapping(manifest, "manifest")
    evidence = _mapping(contract.get("evidence"), "manifest.evidence")
    acceptance = _mapping(contract.get("acceptance"), "manifest.acceptance")
    required_kinds = _string_set(
        evidence.get("required_receipts"),
        "manifest.evidence.required_receipts",
    )
    condition_kinds = _mapping(
        evidence.get("condition_receipt_kinds"),
        "manifest.evidence.condition_receipt_kinds",
    )
    required_conditions = _string_set(
        acceptance.get("manifest_complete_requires"),
        "manifest.acceptance.manifest_complete_requires",
    )
    if set(condition_kinds) != required_conditions:
        raise ValueError("condition receipt mapping MUST match completion conditions")
    if not all(
        isinstance(receipt_kind, str) and receipt_kind in required_kinds
        for receipt_kind in condition_kinds.values()
    ):
        raise ValueError("condition receipt mapping MUST reference required receipt kinds")

    by_kind: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(receipts):
        receipt = _mapping(value, f"receipts[{index}]")
        kind = receipt.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"receipts[{index}].kind MUST be non-empty text")
        if kind in by_kind:
            raise ValueError(f"receipts contains duplicate kind: {kind}")
        provenance = receipt.get("provenance_digest")
        if not isinstance(provenance, str) or _SHA256.fullmatch(provenance) is None:
            raise ValueError(
                f"receipts[{index}].provenance_digest MUST be a lowercase SHA-256 digest"
            )
        by_kind[kind] = receipt

    present_kinds = set(by_kind)
    if present_kinds != required_kinds:
        missing = ", ".join(sorted(required_kinds - present_kinds)) or "none"
        unexpected = ", ".join(sorted(present_kinds - required_kinds)) or "none"
        raise ValueError(
            f"receipt kinds MUST match the manifest; missing: {missing}; unexpected: {unexpected}"
        )
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise ValueError("samples MUST be an array")

    condition_receipts = {
        condition: by_kind[receipt_kind]["provenance_digest"]
        for condition, receipt_kind in sorted(condition_kinds.items())
    }
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "correlation_id": correlation_id,
        "target_revision": target_revision,
        "started_at": started_at,
        "recurrence_observed_at": recurrence_observed_at,
        "receipts": [by_kind[kind] for kind in sorted(by_kind)],
        "condition_receipts": condition_receipts,
        "samples": list(samples),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("receipts_directory", type=Path)
    parser.add_argument("samples", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--recurrence-observed-at", required=True)
    args = parser.parse_args(argv)
    try:
        receipt_paths = sorted(args.receipts_directory.glob("*.json"))
        bundle = build_bundle(
            _load_json(args.manifest),
            [_load_json(path) for path in receipt_paths],
            _load_json(args.samples),
            campaign_id=args.campaign_id,
            correlation_id=args.correlation_id,
            target_revision=args.target_revision,
            started_at=args.started_at,
            recurrence_observed_at=args.recurrence_observed_at,
        )
        output = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        with args.output.open("xb") as stream:
            stream.write(output)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ohl-evidence-builder: ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ohl-evidence-builder: OK: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
