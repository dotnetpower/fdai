#!/usr/bin/env python3
"""Exemption auto-expiry + ahead-of-expiry alert CLI.

Scans every JSON file under `rule-catalog/exemptions/`. For each `active`
exemption whose `expires_at` has passed, either prints what would change
(`--dry-run`, the default) or writes the state transition to disk (`--apply`).
For each `active` exemption whose `expires_at` falls within the configured
ahead-of-expiry alert lead time (`--alert-lead-days`, default 14 -
`AppConfig.rule_governance.exemption_alert_lead_days`), prints an ahead-of-expiry
notice using `plan_exemption_lifecycle`
(rule-governance.md "Exemptions" - scheduled expiry mechanics + ahead-of-expiry
notifications).

This standalone repository scanner never calls a provider or publishes an
execution request. It only reports or persists the reviewed catalog state.
A scheduled runtime uses
`fdai.delivery.exemption_lifecycle.ExemptionLifecycleCoordinator` with
`EventBusExemptionExpiryCommandPublisher` to emit the typed, idempotent
assignment-reapply proposal through the normal action pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionError,
    ExemptionState,
    load_exemption_from_mapping,
    parse_exemption_json,
)
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionLifecycleAction,
    plan_exemption_lifecycle,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _load_all(directory: Path) -> dict[Path, Exemption]:
    """Load every valid exemption under ``directory``, reporting invalid files."""
    loaded: dict[Path, Exemption] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = parse_exemption_json(path.read_text(encoding="utf-8"))
            loaded[path] = load_exemption_from_mapping(raw)
        except (ValueError, ExemptionError) as exc:
            print(f"[skip] {path}: invalid ({exc})", file=sys.stderr)
    return loaded


def _expire_one(path: Path, exemption: Exemption, *, apply: bool) -> bool:
    """Return True if a state change happened (or would happen in dry-run)."""
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


def _report_ahead_of_expiry_alerts(exemptions: list[Exemption], *, alert_lead_days: int) -> int:
    """Print one ahead-of-expiry notice per exemption due for one; return the count.

    This offline CLI has no durable idempotency store, so repeated invocations
    within the lead window print the notice again - the same shape a scheduled
    Container Apps Job sees on every tick until the exemption is resolved or
    expires. A deployment wanting at-most-once delivery + persisted audit
    evidence wires `ExemptionLifecycleCoordinator` instead (see module
    docstring).
    """
    decisions = plan_exemption_lifecycle(
        exemptions, now=_now(), alert_lead=timedelta(days=alert_lead_days)
    )
    alerts = [d for d in decisions if d.action is ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY]
    for decision in alerts:
        print(
            f"[ahead-of-expiry] {decision.exemption_id} (rule={decision.rule_id}) "
            f"expires at {decision.expires_at.isoformat()}"
        )
    return len(alerts)


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
    parser.add_argument(
        "--alert-lead-days",
        type=int,
        default=14,
        help=(
            "Ahead-of-expiry alert lead time in days (default 14 - matches "
            "AppConfig.rule_governance.exemption_alert_lead_days's default)."
        ),
    )
    parser.add_argument(
        "--no-alerts",
        action="store_true",
        help="Skip the ahead-of-expiry alert pass (expiry-only, legacy behavior).",
    )
    args = parser.parse_args(argv)

    if not args.directory.exists():
        print(f"{args.directory} does not exist - nothing to expire.")
        return 0

    exemptions = _load_all(args.directory)

    changed = 0
    for path, exemption in exemptions.items():
        if _expire_one(path, exemption, apply=not args.dry_run):
            changed += 1

    if args.dry_run:
        print(f"\ndry-run: {changed} exemption(s) would transition to expired.")
    else:
        print(f"\napplied: {changed} exemption(s) transitioned to expired.")

    if not args.no_alerts:
        alerted = _report_ahead_of_expiry_alerts(
            list(exemptions.values()), alert_lead_days=args.alert_lead_days
        )
        print(f"ahead-of-expiry: {alerted} exemption(s) are within the alert lead time.")

    return 0


if __name__ == "__main__":  # pragma: no cover - invoked as a script
    raise SystemExit(main())
