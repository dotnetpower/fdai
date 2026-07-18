#!/usr/bin/env python3
"""Exemption auto-expiry CLI stub.

Scans every JSON file under `rule-catalog/exemptions/`, and for each one
whose ``expires_at`` has passed and whose ``state`` is still ``active``,
either prints what would change (``--dry-run``, the default) or writes the
state transition to disk (``--apply``).

Real deployment shape: this script is invoked by a scheduled Container
Apps Job (or an equivalent K8s CronJob) after W4.1 provisions the Azure
infrastructure. Today the script is standalone so the workflow can be
exercised without any cloud dependency.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionError,
    ExemptionState,
    load_exemption_from_mapping,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _expire_one(path: Path, *, apply: bool) -> bool:
    """Return True if a state change happened (or would happen in dry-run)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        exemption = load_exemption_from_mapping(raw)
    except (json.JSONDecodeError, ExemptionError) as exc:
        print(f"[skip] {path}: invalid ({exc})", file=sys.stderr)
        return False

    if exemption.state is not ExemptionState.ACTIVE:
        return False
    if exemption.expires_at > _now():
        return False

    updated = _mark_expired(exemption)
    if apply:
        _write(path, updated)
        print(f"[expired] {path}")
    else:
        print(f"would expire: {path}")
    return True


def _mark_expired(exemption: Exemption) -> dict[str, object]:
    """Build the JSON payload with ``state=expired``."""
    dumped = exemption.model_dump(mode="json")
    dumped["state"] = ExemptionState.EXPIRED.value
    return dumped


def _write(path: Path, payload: dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exemption-expire", description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="rule-catalog/exemptions",
        type=Path,
        help="Directory of exemption JSON files (default: rule-catalog/exemptions).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report what would change; do NOT touch the files (default).",
    )
    group.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Persist the expiry to disk.",
    )
    args = parser.parse_args(argv)

    if not args.directory.exists():
        print(f"{args.directory} does not exist - nothing to expire.")
        return 0

    changed = 0
    for path in sorted(args.directory.glob("*.json")):
        if _expire_one(path, apply=not args.dry_run):
            changed += 1

    if args.dry_run:
        print(f"\ndry-run: {changed} exemption(s) would transition to expired.")
    else:
        print(f"\napplied: {changed} exemption(s) transitioned to expired.")
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked as a script
    raise SystemExit(main())
