#!/usr/bin/env python3
"""Translate a pinned Azure Policy snapshot into inert Rule candidates outside the catalog.

Usage:
    uv run python scripts/catalog/translate-azure-policy-candidates.py \\
        --snapshot-dir <collector snapshot dir> --output-dir <private work dir>

The snapshot directory is the collector's ``rule-catalog/sources``-style output with
``SNAPSHOT.json`` and ``tree/``. Candidates are written as ``candidates/<rule-id>.yaml`` with a
``.translation.json`` record, and their Rego at each candidate's ``check_logic`` reference. The
output directory MUST be outside ``rule-catalog/`` and ``policies/``: candidates stay inert until
a differential comparison and the Mimir quality gate admit them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from fdai.rule_catalog.pipeline.translate.azure_policy import (
    load_alias_map,
    translate_snapshot,
)
from fdai.shared.contracts.models import Rule

_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--alias-map",
        type=Path,
        default=_ROOT / "rule-catalog/translation/azure-policy/aliases.yaml",
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    for protected in (_ROOT / "rule-catalog", _ROOT / "policies"):
        if output == protected.resolve() or protected.resolve() in output.parents:
            print(f"error: output MUST be outside {protected}", file=sys.stderr)
            return 2
    snapshot = json.loads((args.snapshot_dir / "SNAPSHOT.json").read_text(encoding="utf-8"))
    collected_at = str(snapshot["collected_at"])
    result = translate_snapshot(
        args.snapshot_dir / "tree",
        alias_map=load_alias_map(args.alias_map),
        resolved_ref=str(snapshot["resolved_revision"]),
        retrieved_at=collected_at[:19] + "Z",
    )
    candidates = output / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    for item in result.results:
        if item.rule is None or item.rego is None or item.translation is None:
            continue
        Rule.model_validate(item.rule)
        rule_id = str(item.rule["id"])
        (candidates / f"{rule_id}.yaml").write_text(
            yaml.safe_dump(dict(item.rule), sort_keys=False), encoding="utf-8"
        )
        (candidates / f"{rule_id}.translation.json").write_text(
            json.dumps(dict(item.translation), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        rego_path = output / str(item.rule["check_logic"]["reference"])
        rego_path.parent.mkdir(parents=True, exist_ok=True)
        rego_path.write_text(item.rego, encoding="utf-8")
    summary = result.summary()
    (output / "translation-report.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in ("definitions", "outcomes")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
