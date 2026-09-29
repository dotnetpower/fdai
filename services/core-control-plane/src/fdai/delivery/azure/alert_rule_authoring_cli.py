#!/usr/bin/env python3
"""Generate Azure Monitor metric alert inputs from a reviewed metric alert catalog.

The generator is all-or-nothing: any refused entry fails the run and writes nothing, so a
deployment never applies a partial alert set. ``--check`` verifies that an existing output
file is byte-identical to a fresh materialization.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdai.delivery.azure.alert_rule_authoring import materialize_metric_alerts
from fdai.rule_catalog.metric_alerts import (
    MetricAlertCatalogError,
    load_metric_alert_catalog,
)


def _render(catalog: Path) -> tuple[str, list[dict[str, str]]]:
    materialization = materialize_metric_alerts(load_metric_alert_catalog(catalog))
    document = materialization.document()
    refusals = [
        {"alert_id": refusal.alert_id, "reason": refusal.reason}
        for refusal in materialization.refusals
    ]
    return json.dumps(document, indent=2, sort_keys=True) + "\n", refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("rule-catalog/metric-alerts"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        content, refusals = _render(args.catalog)
    except MetricAlertCatalogError as exc:
        print(f"metric-alerts: ERROR: {exc}", file=sys.stderr)
        return 1
    if refusals:
        for refusal in refusals:
            print(
                f"metric-alerts: REFUSED: {refusal['alert_id']}: {refusal['reason']}",
                file=sys.stderr,
            )
        return 1
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else None
        if current != content:
            print(f"metric-alerts: STALE: {args.output}", file=sys.stderr)
            return 1
        print(f"metric-alerts: OK ({args.output})")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(args.output)
    print(f"metric-alerts: wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
