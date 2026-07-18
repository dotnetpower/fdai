"""Catalog-driven chaos-scenario runner.

Unlike `scripts/catalog/run-enforce-scenarios.py` (which hardcodes the 10
upstream reference scenarios) and `scripts/catalog/measure-detection-latency.py`
(same, but with a probing runner), this driver loads scenarios from
`rule-catalog/chaos-scenarios/` and dispatches each through the
:class:`~fdai.core.chaos.factory.ScenarioFactory`. It is the runtime
answer to "the catalog says X; does the delivery layer know how to
execute X?".

Usage:

    # Dry-run: report which entries this composition can execute
    python scripts/catalog/run-catalog-scenario.py --list

    # Dispatch-check (no substrate): build every executable
    # (injector, probe) pair and print PASS / FAIL per entry
    python scripts/catalog/run-catalog-scenario.py --dry-run

    # Enforce one scenario end-to-end against the FDAI_ENFORCE_* substrate
    python scripts/catalog/run-catalog-scenario.py --run chaos.chaos-mesh.pod-failure \
        --confirm-enforce

    # Enforce every executable entry (safe: needs-injector entries
    # are filtered out before injection)
    python scripts/catalog/run-catalog-scenario.py --run-all --confirm-enforce

Substrate config comes from the same `FDAI_ENFORCE_*` env vars the
other enforce runners read; see `scripts/catalog/run-enforce-scenarios.py` for
the full list. Enforce modes also require `FDAI_ENFORCE_APPROVAL_REF`
and the explicit `--confirm-enforce` flag. The approval reference is
recorded in every result; validation against the authoritative HIL
state belongs to the promotion evidence contract. Missing inputs fail
fast; `--list` and `--dry-run` need no env vars.

Reports land under `logs/catalog-runs/<timestamp>/`. Every run writes
one JSON per scenario plus a `report.json` + `summary.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.chaos.catalog_evidence import (
    CatalogEvidenceLevel,
    build_catalog_validation_summary,
    write_catalog_validation_summary,
)
from fdai.core.chaos.contract import ExperimentResult, FaultScenario
from fdai.core.chaos.factory import ScenarioFactory, UnavailableInjectorError
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    load_promotion_ledger,
)
from fdai.core.chaos.scenario_catalog import (
    CatalogEntry,
    catalog_fingerprint,
    load_all,
    load_promoted,
)
from fdai.delivery.chaos.factories import default_factory
from fdai.shared.contracts.models import Mode


def _env_or_none(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v else None


def _substrate_context() -> dict[str, Any]:
    """Read FDAI_ENFORCE_* env vars; fail fast when any is missing."""
    required = {
        "FDAI_ENFORCE_SUB_ID": "sub_id",
        "FDAI_ENFORCE_RG": "resource_group",
        "FDAI_ENFORCE_AKS_CONTEXT": "kubectl_context",
        "FDAI_ENFORCE_NS": "workload_namespace",
        "FDAI_ENFORCE_CHAOS_NS": "chaos_namespace",
        "FDAI_ENFORCE_BACKEND_DEPLOY": "backend_deployment",
        "FDAI_ENFORCE_BACKEND_SVC": "backend_service",
        "FDAI_ENFORCE_BACKEND_LABEL": "workload_label_raw",
        "FDAI_ENFORCE_VM": "vm_name",
        "FDAI_ENFORCE_PROMOTION_EVIDENCE": "promotion_evidence_path",
    }
    missing = [env for env in required if not os.environ.get(env)]
    if missing:
        raise SystemExit(f"missing required env vars for --run / --run-all: {', '.join(missing)}")
    ctx: dict[str, Any] = {name: os.environ[env] for env, name in required.items()}
    # Normalize the workload_label: BACKEND_LABEL is `app=api-backend`,
    # but the CRD body just needs the value on the right of `=`.
    raw = ctx.pop("workload_label_raw")
    ctx["workload_label"] = raw.split("=", 1)[-1] if "=" in raw else raw
    ctx["vm_resource_id"] = (
        f"/subscriptions/{ctx['sub_id']}/resourceGroups/{ctx['resource_group']}"
        f"/providers/Microsoft.Compute/virtualMachines/{ctx['vm_name']}"
    )
    ctx["backend_container"] = os.environ.get("FDAI_ENFORCE_BACKEND_CONTAINER", "web")
    ctx["backend_restore_replicas"] = int(os.environ.get("FDAI_ENFORCE_BACKEND_REPLICAS", "3"))
    ctx["backend_image"] = os.environ.get("FDAI_ENFORCE_BACKEND_IMAGE", "nginx")
    return ctx


def _with_promotion_approval(
    entry: CatalogEntry,
    ctx: dict[str, Any],
    catalog_entries: list[CatalogEntry],
) -> dict[str, Any]:
    evidence_path = Path(str(ctx["promotion_evidence_path"]))
    ledger = load_promotion_ledger(evidence_path)
    key = ScenarioEvidenceKey(
        scenario_id=entry.id,
        scenario_version=int(entry.spec["version"]),
        catalog_fingerprint=catalog_fingerprint(catalog_entries),
    )
    approval_ref = ledger.approval_ref_for(key)
    if approval_ref is None:
        raise SystemExit(
            f"{entry.id!r} is not enforce-eligible for the current catalog fingerprint"
        )
    approved = dict(ctx)
    approved.pop("promotion_evidence_path", None)
    approved["approval_ref"] = approval_ref
    return approved


def _serialize(result: ExperimentResult) -> dict[str, Any]:
    d = dataclasses.asdict(result)
    d["mode"] = result.mode.value
    d["outcome"] = result.outcome.value
    d["started_at"] = result.started_at.isoformat()
    d["ended_at"] = result.ended_at.isoformat()
    d["targets"] = list(result.targets)
    d["reverted"] = result.reverted
    return d


async def _run_one(
    entry: CatalogEntry,
    factory: ScenarioFactory,
    ctx: dict[str, Any],
    out_dir: Path,
    max_hold_seconds: float,
) -> dict[str, Any]:
    """Build injector + probe, run the harness once, persist JSON."""
    payload: dict[str, Any]
    t0 = time.monotonic()
    try:
        injector, probe = factory.build(entry, ctx)
    except (UnavailableInjectorError, Exception) as exc:  # noqa: BLE001 - reported as JSON
        payload = {
            "scenario_id": entry.id,
            "outcome": "build_error",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - t0, 2),
            "approval_ref": ctx["approval_ref"],
        }
        (out_dir / f"{_slugify(entry.id)}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        print(f"[build_error] {entry.id}: {exc}", flush=True)
        return payload

    scenario = _to_fault_scenario(entry)
    approved_targets = [
        os.environ.get("FDAI_ENFORCE_BACKEND_LABEL", ctx.get("workload_label", "api-backend"))
    ]
    harness = FaultInjectionHarness(
        injectors=[injector],
        probe=probe,
        operation_timeout_seconds=180.0,
        rollback_timeout_seconds=180.0,
        max_hold_seconds=max_hold_seconds,
    )
    try:
        result = await harness.run(scenario, approved_targets=approved_targets, mode=Mode.ENFORCE)
        payload = _serialize(result)
        payload["elapsed_seconds"] = round(time.monotonic() - t0, 2)
        payload["approval_ref"] = ctx["approval_ref"]
    except Exception as exc:  # noqa: BLE001 - report driver errors
        payload = {
            "scenario_id": entry.id,
            "outcome": "driver_error",
            "error": f"{type(exc).__name__}:{exc}",
            "elapsed_seconds": round(time.monotonic() - t0, 2),
            "approval_ref": ctx["approval_ref"],
        }
    (out_dir / f"{_slugify(entry.id)}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[{payload.get('outcome', '?')}] {entry.id} "
        f"detected={payload.get('detected')} "
        f"reverted={payload.get('reverted')} "
        f"elapsed={payload.get('elapsed_seconds')}s",
        flush=True,
    )
    return payload


def _slugify(scenario_id: str) -> str:
    return scenario_id.replace(".", "-").replace("/", "-")


def _to_fault_scenario(entry: CatalogEntry) -> FaultScenario:
    """Adapt a CatalogEntry to the harness's FaultScenario dataclass."""
    return FaultScenario(
        scenario_id=entry.id,
        fault_type=str(entry.spec.get("fault_family", "unknown")),
        description=str(entry.spec.get("description", entry.id)),
        target_selector=f"catalog:{entry.id}",
        expected_signal=str(entry.expected_signal),
        blast_radius_cap=int(entry.spec.get("blast_radius_cap", 1)),
        duration_seconds=float(entry.spec.get("duration_seconds", 360.0)),
        params={str(k): str(v) for k, v in (entry.spec.get("params") or {}).items()},
        rollback_note=str(entry.spec.get("rollback_note", "")),
    )


def _list_command(factory: ScenarioFactory) -> int:
    entries = load_all()
    executable = factory.executable_entries(entries)
    non_exec = [e for e in entries if e not in executable]
    print(f"catalog: {len(entries)} entries")
    print(f"executable via default factory: {len(executable)}")
    print(f"non-executable (needs-injector or missing probe): {len(non_exec)}")
    if len(executable):
        print("\nexecutable ids:")
        for e in executable:
            print(f"  - {e.id}  injector={e.spec['injector']}  signal={e.expected_signal}")
    return 0


async def _dry_run(factory: ScenarioFactory, summary_path: Path | None = None) -> int:
    """Build every executable pair with a synthetic context; report per-entry PASS/FAIL."""
    ctx = {
        "sub_id": "00000000-0000-0000-0000-000000000000",
        "kubectl_context": "dry-ctx",
        "workload_namespace": "demo",
        "workload_label": "api-backend",
        "chaos_namespace": "chaos-mesh",
        "litmus_namespace": "litmus",
        "litmus_service_account": "litmus-admin",
        "litmus_target_node": "node-test",
        "backend_deployment": "api-backend",
        "backend_service": "api-backend",
        "backend_container": "web",
        "backend_restore_replicas": 3,
        "backend_image": "nginx",
        "resource_group": "rg-test",
        "vm_name": "vm-test",
        "vmss_name": "vmss-test",
        "redis_cache_name": "redis-test",
        "cosmos_account_name": "cosmos-test",
        "keyvault_name": "kv-test",
        "nsg_name": "nsg-test",
        "lb_name": "lb-test",
        "lb_pool_name": "pool-test",
        "lb_address_name": "addr-test",
        "servicebus_namespace": "sb-test",
        "mysql_connect_factory": lambda: None,
        "mysql_server_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-test/providers/Microsoft.DBforMySQL/"
            "flexibleServers/mysql-test"
        ),
        "aoai_load_request_fn": lambda: 200,
        "aoai_probe_request_fn": lambda: 429,
        "gpu_sku_assessment_fn": lambda _targets: {
            "observed_sku": "H100",
            "recommended_sku": "A100",
            "confidence": 0.9,
        },
        "vm_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-test"
        ),
    }
    all_entries = load_all()
    entries = factory.executable_entries(all_entries)
    fails = 0
    reports: dict[str, dict[str, object]] = {}
    for e in entries:
        try:
            factory.build(e, ctx)
        except Exception as exc:  # noqa: BLE001 - dry-run: never raise
            fails += 1
            reports[e.id] = {"outcome": "build_error"}
            print(f"FAIL {e.id}: {type(exc).__name__}:{exc}", flush=True)
        else:
            reports[e.id] = {"outcome": "dispatchable"}
    if summary_path is not None:
        summary = build_catalog_validation_summary(
            entries=all_entries,
            reports=reports,
            evidence_level=CatalogEvidenceLevel.DISPATCHABILITY,
            runner_version="run-catalog-scenario/1",
        )
        write_catalog_validation_summary(summary, summary_path)
    print(f"\ndry-run: {len(entries) - fails}/{len(entries)} entries dispatchable", flush=True)
    return 1 if fails else 0


async def _run_one_by_id(scenario_id: str, factory: ScenarioFactory) -> int:
    all_entries = load_all()
    entries = [e for e in load_promoted() if e.id == scenario_id]
    if not entries:
        raise SystemExit(f"scenario id {scenario_id!r} not found in the promoted runtime catalog")
    entry = entries[0]
    if not factory.is_executable(entry):
        raise SystemExit(
            f"{scenario_id!r} is not executable via the default factory "
            f"(injector={entry.spec['injector']!r}, signal={entry.expected_signal!r})"
        )
    ctx = _with_promotion_approval(entry, _substrate_context(), all_entries)
    out_dir = _report_dir()
    max_hold = float(os.environ.get("FDAI_MAX_HOLD_SECONDS", "180"))
    payload = await _run_one(entry, factory, ctx, out_dir, max_hold)
    (out_dir / "report.json").write_text(json.dumps({"runs": [payload]}, indent=2, sort_keys=True))
    _write_summary(out_dir, [payload])
    return 0 if payload.get("outcome") == "validated" else 1


async def _run_all(factory: ScenarioFactory, limit: int | None) -> int:
    all_entries = load_all()
    entries = factory.executable_entries(load_promoted())
    if limit is not None:
        entries = entries[:limit]
    out_dir = _report_dir()
    max_hold = float(os.environ.get("FDAI_MAX_HOLD_SECONDS", "180"))
    reports: list[dict[str, Any]] = []
    for e in entries:
        ctx = _with_promotion_approval(e, _substrate_context(), all_entries)
        reports.append(await _run_one(e, factory, ctx, out_dir, max_hold))
        await asyncio.sleep(10)
    (out_dir / "report.json").write_text(json.dumps({"runs": reports}, indent=2, sort_keys=True))
    _write_summary(out_dir, reports)
    validated = sum(1 for r in reports if r.get("outcome") == "validated")
    print(f"\nsummary: {validated}/{len(reports)} validated  ->  {out_dir}", flush=True)
    return 0 if validated == len(reports) else 1


def _report_dir() -> Path:
    root = Path("logs/catalog-runs") / datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_summary(out_dir: Path, reports: list[dict[str, Any]]) -> None:
    lines = [
        "# Catalog run summary",
        "",
        f"Report root: `{out_dir}`",
        "",
        "| Scenario | Outcome | Detected | Reverted | Elapsed (s) | Error |",
        "|----------|---------|----------|----------|-------------|-------|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.get('scenario_id')}` | {r.get('outcome')} | "
            f"{r.get('detected')} | {r.get('reverted')} | "
            f"{r.get('elapsed_seconds')} | {r.get('error') or ''} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--list",
        action="store_true",
        help="Report executable coverage; no substrate needed.",
    )
    grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Build every executable pair with a synthetic context; no substrate needed.",
    )
    grp.add_argument("--run", metavar="SCENARIO_ID", help="Enforce one scenario end-to-end.")
    grp.add_argument(
        "--run-all",
        action="store_true",
        help="Enforce every executable scenario end-to-end.",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="Cap on --run-all (executes the first N executable entries).",
    )
    p.add_argument(
        "--confirm-enforce",
        action="store_true",
        help="Confirm that the already-approved run may mutate the disposable substrate.",
    )
    p.add_argument(
        "--evidence-summary",
        type=Path,
        help="Write a sanitized, fingerprint-bound validation summary.",
    )
    args = p.parse_args(argv)

    factory = default_factory()

    if args.list:
        return _list_command(factory)
    if args.dry_run:
        return asyncio.run(_dry_run(factory, args.evidence_summary))
    if not args.confirm_enforce:
        raise SystemExit("--run / --run-all requires explicit --confirm-enforce")
    if args.run:
        return asyncio.run(_run_one_by_id(args.run, factory))
    if args.run_all:
        return asyncio.run(_run_all(factory, args.limit))
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
