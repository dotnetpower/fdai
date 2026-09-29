"""Measure chaos detection latency only through the governed adapter.

The driver selects one catalog or reference scenario, resolves the same
deployment-owned governed bindings as `run-catalog-scenario.py`, and emits one
JSON record. An unbound checkout refuses before reading substrate context.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

from fdai.core.chaos.scenario_catalog import catalog_fingerprint
from fdai.delivery.chaos.governed_records import catalog_enforce_request
from fdai.delivery.chaos.mutation_scope import approved_catalog_targets
from fdai.shared.contracts.models import Tier
from fdai.shared.providers.tool import ToolError

REFUSED_EXIT = 3
_DEFAULT_SCENARIO = "aks-pod-kill"
_RUNNER_MODULE: ModuleType | None = None


def _load_catalog_runner() -> ModuleType:
    """Load the sibling runner so this driver reuses its governed helpers."""

    global _RUNNER_MODULE  # noqa: PLW0603 - test patch point for this script
    if _RUNNER_MODULE is not None:
        return _RUNNER_MODULE
    path = Path(__file__).with_name("run-catalog-scenario.py")
    spec = importlib.util.spec_from_file_location("fdai_run_catalog_scenario", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("run-catalog-scenario.py is not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _RUNNER_MODULE = module
    return module


def _emit(record: dict[str, object], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(record, sort_keys=True), file=stream, flush=True)


def _latency_value(value: float | None) -> float | str:
    return "unknown" if value is None else value


async def _measure(scenario_id: str) -> int:
    runner = _load_catalog_runner()
    out_dir = runner._report_dir()
    try:
        bindings = runner._governed_bindings()
        approval_ref = runner._approval_claim()
        context = runner._substrate_context()
        action_type = runner._chaos_action_type()
        factory = runner.default_factory()
        all_entries = runner.load_all()
        promoted = runner.load_promoted()
        entries = runner._select_entries(
            factory,
            promoted,
            scenario_id=scenario_id,
            sweep=False,
            limit=None,
        )
        entry = entries[0]
        targets = approved_catalog_targets(entry, context)
        if targets is None:
            raise runner._EnforceRefusalError(
                "target_type_unsupported",
                f"target_type {entry.spec.get('target_type')!r} has no substrate identity",
            )
    except runner._EnforceRefusalError as refusal:
        return cast(int, runner._refuse(out_dir, refusal))

    adapter = runner.GovernedChaosExecutionAdapter(
        entries=all_entries,
        promoted_ids=frozenset(item.id for item in promoted),
        factory=factory,
        context=context,
        bindings=bindings,
        action_type=action_type,
        max_hold_seconds=float(runner.os.environ.get("FDAI_MAX_HOLD_SECONDS", "180")),
    )
    request = catalog_enforce_request(
        entry,
        targets=targets,
        approval_ref=approval_ref,
        fingerprint=catalog_fingerprint(all_entries),
        stop_conditions=tuple(action_type.stop_conditions),
        tier=Tier.T0,
    )
    payload: dict[str, object] = {
        "driver": "measure-detection-latency",
        "scenario": entry.id,
        "outcome": "adapter_error",
        "detected": None,
        "detection_latency_seconds": "unknown",
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    try:
        outcome = await adapter.run(request)
    except ToolError as exc:
        payload.update(outcome=f"refused_{exc.kind}", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - measurement driver fails closed
        payload.update(outcome="adapter_error", error=type(exc).__name__)
    else:
        experiment = outcome.experiment
        payload.update(
            outcome=outcome.receipt.outcome.value,
            run_id=outcome.receipt.receipt_ref,
            detail=outcome.receipt.detail,
            detected=outcome.detected,
            experiment_outcome=outcome.experiment_outcome,
            passed=outcome.passed,
        )
        if experiment is not None:
            payload["detection_latency_seconds"] = _latency_value(
                experiment.detection_latency_seconds
            )
    _emit(payload)
    return 0 if payload.get("detection_latency_seconds") != "unknown" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default=_DEFAULT_SCENARIO,
        help="Catalog id or reviewed reference scenario id to measure.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the selected scenario without resolving governed bindings.",
    )
    parser.add_argument(
        "--confirm-enforce",
        action="store_true",
        help="Confirm the operator intends a governed run on the disposable substrate.",
    )
    args = parser.parse_args(argv)
    if args.dry_run:
        _emit(
            {
                "driver": "measure-detection-latency",
                "scenario": args.scenario,
                "outcome": "dry_run",
                "detected": None,
                "detection_latency_seconds": "unknown",
                "mutation_attempted": False,
            }
        )
        return 0
    if not args.confirm_enforce:
        _emit(
            {
                "driver": "measure-detection-latency",
                "mode": "enforce",
                "outcome": "refused",
                "reason": "enforce_confirmation_required",
                "mutation_attempted": False,
            },
            error=True,
        )
        return REFUSED_EXIT
    return asyncio.run(_measure(str(args.scenario)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
