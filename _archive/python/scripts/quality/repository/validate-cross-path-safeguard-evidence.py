#!/usr/bin/env python3
"""Validate the cross-path safeguard evidence contract and any built bundle.

Two jobs, deliberately separated:

1. The contract itself is always checked - schema validity, a complete
   4x2x2 matrix with no duplicate or missing cell, honest denial reasons,
   and residuals that stay listed while the campaign is `prepared`.
2. A bundle, when supplied, is checked against that contract - same pinned
   revision, every eligible cell observed, every denial class exercised, no
   synthetic evidence, and a digest that still matches its own bytes.

The verifier fails closed: an unreadable, unparsable, or partially complete
input is a failure, never a pass with a warning. It performs no network call
and no effect.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_PATH = _ROOT / "config/cross-path-safeguard-evidence.json"
_SCHEMA_PATH = _ROOT / "config/cross-path-safeguard-evidence.schema.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXECUTION_PATHS = ("pr_native", "pr_manual", "direct_api", "tool_call")
EXECUTION_ORIGINS = ("core", "workflow")
EXECUTION_VENUES = ("core", "isolated_executor")


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load(path: Path) -> Mapping[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError(f"{path.name}: document MUST be a JSON object")
    return document


def validate_contract(contract: Mapping[str, Any]) -> list[str]:
    """Check the predeclared matrix independently of any campaign run."""

    errors: list[str] = []
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    for failure in sorted(
        Draft202012Validator(schema).iter_errors(dict(contract)),
        key=lambda item: list(item.path),
    ):
        errors.append(f"contract schema: {list(failure.path)}: {failure.message}")
    if errors:
        return errors

    matrix = contract["matrix"]
    seen: set[str] = set()
    for cell in matrix:
        cell_id = str(cell["cell_id"])
        if cell_id in seen:
            errors.append(f"matrix: duplicate cell {cell_id}")
        seen.add(cell_id)
        expected = f"{cell['execution_path']}:{cell['execution_origin']}:{cell['execution_venue']}"
        if cell_id != expected:
            errors.append(f"matrix: cell id {cell_id} does not match its own axes")

    expected_ids = {
        f"{path}:{origin}:{venue}"
        for path in EXECUTION_PATHS
        for origin in EXECUTION_ORIGINS
        for venue in EXECUTION_VENUES
    }
    for missing in sorted(expected_ids - seen):
        errors.append(f"matrix: missing cell {missing}")
    for extra in sorted(seen - expected_ids):
        errors.append(f"matrix: cell {extra} invents an axis value")

    if contract["status"] == "prepared" and contract["evidence_level"] != "contract_only":
        errors.append("a prepared campaign has produced no live effect")
    if contract["status"] == "prepared" and not contract["residuals"]:
        errors.append("a prepared campaign MUST list what is still missing")
    if contract["evidence_level"] == "live_execution" and contract["residuals"]:
        errors.append("a live campaign MUST NOT still carry residuals")
    return errors


def validate_bundle(
    contract: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> list[str]:
    """Check one built bundle against the contract it claims to satisfy."""

    errors: list[str] = []
    digest = str(bundle.get("bundle_digest", ""))
    if not _SHA256.fullmatch(digest):
        return ["bundle: bundle_digest MUST be a SHA-256 hex digest"]
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    if hashlib.sha256(_canonical(body)).hexdigest() != digest:
        errors.append("bundle: digest does not match its own bytes")
    if hashlib.sha256(_canonical(contract)).hexdigest() != bundle.get("contract_digest"):
        errors.append("bundle: contract digest does not match the current contract")

    base_revision = contract["base_revision"]
    if bundle.get("base_revision") != base_revision:
        errors.append("bundle: pinned revision differs from the contract")

    receipts = bundle.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        return errors + ["bundle: receipts MUST be a non-empty list"]

    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            errors.append("bundle: every receipt MUST be a JSON object")
            continue
        if receipt.get("base_revision") != base_revision:
            errors.append(f"bundle: receipt {receipt.get('cell_id')} pins another revision")
        if receipt.get("synthetic") is not False:
            errors.append(f"bundle: receipt {receipt.get('cell_id')} is synthetic")
        if receipt.get("authority_class") != "no_authority":
            errors.append(f"bundle: receipt {receipt.get('cell_id')} claims authority")

    observed = {
        str(receipt["cell_id"])
        for receipt in receipts
        if isinstance(receipt, Mapping) and receipt.get("kind") == "observation"
    }
    eligible = {
        str(cell["cell_id"]) for cell in contract["matrix"] if cell["eligibility"] == "eligible"
    }
    for missing in sorted(eligible - observed):
        errors.append(f"bundle: eligible cell {missing} has no independent observation")

    denied = {
        str(receipt["cell_id"])
        for receipt in receipts
        if isinstance(receipt, Mapping) and receipt.get("kind") == "denial_class"
    }
    declared = {
        f"{group}:{name}" for group, names in contract["denial_classes"].items() for name in names
    }
    for missing in sorted(declared - denied):
        errors.append(f"bundle: denial class {missing} was never exercised")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the contract, and a bundle when one is supplied."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=None,
        help="Optional built evidence bundle to check against the contract.",
    )
    args = parser.parse_args(argv)

    try:
        contract = _load(_CONTRACT_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cross-path-safeguard-evidence: ERROR: {exc}", file=sys.stderr)
        return 1

    errors = validate_contract(contract)
    if args.bundle is not None and not errors:
        try:
            errors.extend(validate_bundle(contract, _load(args.bundle)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"bundle: {exc}")

    for error in errors:
        print(f"cross-path-safeguard-evidence: {error}", file=sys.stderr)
    if errors:
        print(
            f"cross-path-safeguard-evidence: FAILED with {len(errors)} violation(s).",
            file=sys.stderr,
        )
        return 1
    scope = "contract and bundle" if args.bundle is not None else "contract"
    print(f"cross-path-safeguard-evidence: OK ({scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
