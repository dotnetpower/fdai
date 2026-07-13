"""CLI entrypoint for the manual-distillation pipeline (build-time, inert).

Usage
-----

    python -m fdai.rule_catalog.pipeline.distill_cli \\
        --drop-dir rule-catalog/manuals-drop \\
        [--snapshot .distill-snapshot.json] [--json]

Runs one incremental distillation pass over a drop directory using the upstream
default seams (:class:`AbstainingManualClassifier`, :class:`AbstainingDistiller`)
and prints a summary of the resulting :class:`DistillationPlan`. With the
upstream defaults nothing is auto-distilled (every candidate routes to HIL as
uncertain) - the pass still exercises the deterministic triage, sensitivity, and
freshness / deletion stages. A fork wires an LLM-backed classifier + distiller
through the composition root to make the ``distilled`` bucket non-empty.

The plan is inert: nothing here mutates the catalog or executes. Promotion of a
distilled candidate stays a separate, human-gated step.

Exits:

- ``0`` - pass completed (summary printed, snapshot written if requested).
- ``64`` - usage error (missing / invalid drop directory).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from fdai.rule_catalog.pipeline.distill.orchestrator import (
    DistillationPlan,
    build_distillation_plan,
)
from fdai.shared.providers.distiller import AbstainingDistiller
from fdai.shared.providers.manual_classifier import AbstainingManualClassifier
from fdai.shared.providers.manual_source import DropDirectoryManualSource

_USAGE_ERROR = 64


def _load_snapshot(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"snapshot {path} MUST be a JSON object of source_ref -> sha")
    return {str(k): str(v) for k, v in raw.items()}


def _summary(plan: DistillationPlan) -> dict[str, object]:
    held_by_reason: dict[str, int] = {}
    for held in plan.held:
        held_by_reason[held.reason] = held_by_reason.get(held.reason, 0) + 1
    return {
        "distilled_manuals": len(plan.distilled),
        "distilled_candidates": plan.distilled_candidate_count,
        "held": len(plan.held),
        "held_by_reason": held_by_reason,
        "rejected": len(plan.rejected),
        "filtered": len(plan.filtered),
        "retirements": [r.source_ref for r in plan.retirements],
        "snapshot_size": len(plan.snapshot),
        "suspected_source_outage": plan.suspected_source_outage,
    }


async def _run(drop_dir: Path, snapshot_path: Path | None) -> DistillationPlan:
    source = DropDirectoryManualSource(drop_dir)
    plan = await build_distillation_plan(
        source=source,
        classifier=AbstainingManualClassifier(),
        distiller=AbstainingDistiller(),
        previous_snapshot=_load_snapshot(snapshot_path),
    )
    if snapshot_path is not None and not plan.suspected_source_outage:
        snapshot_path.write_text(
            json.dumps(dict(plan.snapshot), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="distill_cli", description=__doc__)
    parser.add_argument("--drop-dir", required=True, type=Path, help="manuals drop directory")
    parser.add_argument("--snapshot", type=Path, help="prior/next snapshot JSON path")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args(argv)

    drop_dir: Path = args.drop_dir
    if not drop_dir.is_dir():
        print(f"error: drop directory not found: {drop_dir}", file=sys.stderr)
        return _USAGE_ERROR

    plan = asyncio.run(_run(drop_dir, args.snapshot))
    summary = _summary(plan)

    if plan.suspected_source_outage:
        print(
            "warning: source returned an empty listing over a non-empty prior "
            "snapshot - suspected source outage; no retirements planned, snapshot "
            "preserved.",
            file=sys.stderr,
        )

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"distilled manuals   : {summary['distilled_manuals']}")
        print(f"distilled candidates: {summary['distilled_candidates']}")
        print(f"held (HIL)          : {summary['held']} {summary['held_by_reason']}")
        print(f"rejected            : {summary['rejected']}")
        print(f"filtered (triage)   : {summary['filtered']}")
        print(f"retirements         : {summary['retirements']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
