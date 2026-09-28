"""Catalog-driven chaos-scenario runner.

This driver loads scenarios from `rule-catalog/chaos-scenarios/` and dispatches
each through the :class:`~fdai.core.chaos.factory.ScenarioFactory`. It is the
runtime answer to "the catalog says X; does the delivery layer know how to
execute X?", and it is the only live chaos path: the retired raw drivers were
removed, and `scripts/catalog/measure-detection-latency.py` still refuses every
live run until its measurement is ported onto the governed adapter.

Usage:

    # Dry-run: report which entries this composition can execute
    python scripts/catalog/run-catalog-scenario.py --list

    # Dispatch-check (no substrate): build every executable
    # (injector, probe) pair and print PASS / FAIL per entry
    python scripts/catalog/run-catalog-scenario.py --dry-run

    # Governed enforce of one promoted scenario against the FDAI_ENFORCE_* substrate
    python scripts/catalog/run-catalog-scenario.py --run chaos.chaos-mesh.pod-failure \
        --confirm-enforce

    # The same governed enforce selected by its reference scenario id
    python scripts/catalog/run-catalog-scenario.py --run aks-pod-cpu-spike --confirm-enforce

    # Governed enforce of the reference sweep, in demo order
    python scripts/catalog/run-catalog-scenario.py --run-sweep --confirm-enforce

    # Governed enforce of every executable promoted entry, one at a time
    python scripts/catalog/run-catalog-scenario.py --run-all --confirm-enforce

    # Release the targets of an escalated or orphaned run after manual recovery;
    # FDAI_CHAOS_CLOSURE_APPROVAL_REF names a separate closure approval by a
    # distinct Var approver, never the approval that authorized the injection
    python scripts/catalog/run-catalog-scenario.py --close chaos.chaos-mesh.pod-failure \
        --confirm-closure --closure-reason "fault absent and workload healthy"

Enforce modes never construct a fault-injection harness here. Each selected
scenario becomes one typed `tool.run-chaos-experiment` enforce request that the
`GovernedChaosExecutionAdapter` runs through `GovernedChaosRunner`. The adapter's
state store, promotion sources, Var approval verifier, run planner, recovery
dispatcher, recovery evidence collector, and target lock come from exactly one
installed `fdai.governed_chaos` entry point named `catalog-scenario`. Without
that provider, enforce refuses before substrate access, writes a structured
refusal report, and exits with status 3.

`--run-sweep` and a reference scenario id passed to `--run` select reviewed
catalog entries through `fdai.core.chaos.reference_sweep`. Selection grants no
authority: a mapped entry still has to be promoted, executable, and target-
resolvable, so an unpromoted sweep refuses exactly like any other enforce.

`FDAI_ENFORCE_APPROVAL_REF` names the current human approval for the injected
verifier to check; it is a claim, never approval by itself. Substrate context
comes from the `FDAI_ENFORCE_*` env vars. Each run's targets are the canonical
identities of the resources its `target_type` mutates (the VM for `vm`, the
workload pods for `pod`, `disk`, and `dns`); other target types are refused.
Requests are deterministic T0 operator submissions, so the ActionType tier
ceiling applies. The request idempotency key binds the scenario version,
catalog fingerprint, targets, and approval claim, so rerunning a command
replays or resumes the durable run instead of injecting again. A run passes
only when it recovered and detected its expected signal; the command exits
non-zero otherwise, and a sweep halts after any run whose rollback is not
verified. `--list` and `--dry-run` need no env vars. This command still calls
the adapter directly rather than through the Core proposal, risk, Var, and
Thor pipeline; that routing remains open work.

Reports land under `logs/catalog-runs/<timestamp>/`. Every run writes
one JSON per scenario plus a `report.json` + `summary.md`. Runs that produced a
measured experiment also land in `enforce-report.json`, the importable contract
`fdai.delivery.chaos.enforce_report` reads into the durable report feed.
`--measured-report <path>` additionally writes that same measured report to an
exact path, so a deployment can pin it where its evidence projection reads.
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

import yaml
from fdai.core.chaos.catalog_evidence import (
    CatalogEvidenceLevel,
    build_catalog_validation_summary,
    write_catalog_validation_summary,
)
from fdai.core.chaos.contract import ExperimentResult
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.reference_sweep import (
    reference_sweep_catalog_ids,
    resolve_scenario_id,
)
from fdai.core.chaos.scenario_catalog import (
    CatalogEntry,
    catalog_fingerprint,
    load_all,
    load_promoted,
)
from fdai.delivery.chaos.enforce_report import enforce_report_record
from fdai.delivery.chaos.factories import default_factory
from fdai.delivery.chaos.governed import GovernedChaosExecutionAdapter
from fdai.delivery.chaos.governed_bindings import (
    GovernedChaosBindings,
    load_governed_chaos_bindings,
)
from fdai.delivery.chaos.governed_closure import GovernedChaosClosure
from fdai.delivery.chaos.governed_records import CHAOS_ACTION_TYPE, catalog_enforce_request
from fdai.delivery.chaos.mutation_scope import approved_catalog_targets
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.shared.contracts.models import Mode, OntologyActionType, Tier
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.tool import ToolCallRequest, ToolError

_REFUSED_EXIT = 3
_SETTLE_SECONDS = 10.0
_CHAOS_ACTION_TYPE_PATH = (
    Path(__file__).resolve().parents[2]
    / "rule-catalog"
    / "action-types"
    / f"{CHAOS_ACTION_TYPE}.yaml"
)


class _EnforceRefusalError(Exception):
    """An enforce precondition failed before any request reached the adapter."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _env_or_none(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v else None


def _substrate_context() -> dict[str, Any]:
    """Read FDAI_ENFORCE_* env vars; refuse when any is missing."""
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
    }
    missing = [env for env in required if not os.environ.get(env)]
    if missing:
        raise _EnforceRefusalError(
            "substrate_context_missing",
            f"missing required env vars for --run / --run-all: {', '.join(missing)}",
        )
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


def _slugify(scenario_id: str) -> str:
    return scenario_id.replace(".", "-").replace("/", "-")


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


def _governed_bindings() -> GovernedChaosBindings:
    """Resolve the one installed provider; an unbound checkout refuses enforce."""

    try:
        bindings = load_governed_chaos_bindings(os.environ)
    except Exception as exc:  # noqa: BLE001 - a broken provider refuses enforce
        raise _EnforceRefusalError("governed_execution_invalid", type(exc).__name__) from exc
    if bindings is None:
        raise _EnforceRefusalError(
            "governed_execution_unbound",
            "install exactly one fdai.governed_chaos entry point named catalog-scenario",
        )
    return bindings


def _approval_claim(variable: str = "FDAI_ENFORCE_APPROVAL_REF") -> str:
    value = os.environ.get(variable, "").strip()
    if not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise _EnforceRefusalError(
            "approval_claim_missing",
            f"{variable} must name the current approval to verify",
        )
    return value


def _chaos_action_type() -> OntologyActionType:
    """Load the validated chaos ActionType for its stop conditions and tier ceilings."""

    try:
        raw = yaml.safe_load(_CHAOS_ACTION_TYPE_PATH.read_text(encoding="utf-8"))
        return load_action_type_from_mapping(
            raw,
            schema_registry=PackageResourceSchemaRegistry(),
            origin=_CHAOS_ACTION_TYPE_PATH.name,
        )
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise _EnforceRefusalError("action_type_unavailable", type(exc).__name__) from exc


def _select_entries(
    factory: ScenarioFactory,
    promoted: list[CatalogEntry],
    *,
    scenario_id: str | None,
    sweep: bool,
    limit: int | None,
) -> list[CatalogEntry]:
    """Return the executable promoted entries one enforce command may run.

    ``scenario_id`` accepts a catalog id or a reference scenario id. ``sweep``
    selects the reference sweep in demo order and keeps that order rather than
    catalog order, so a halted sweep stops at the declared scenario.
    """

    entries = factory.executable_entries(promoted)
    if sweep:
        by_id = {entry.id: entry for entry in entries}
        entries = [
            by_id[catalog_id] for catalog_id in reference_sweep_catalog_ids() if catalog_id in by_id
        ]
        selection = "--run-sweep"
    elif scenario_id is not None:
        wanted = resolve_scenario_id(scenario_id)
        entries = [entry for entry in entries if entry.id == wanted]
        selection = scenario_id
    else:
        if limit is not None:
            entries = entries[:limit]
        selection = "--run-all"
    if not entries:
        raise _EnforceRefusalError(
            "no_executable_promoted_scenario",
            f"no executable promoted scenario matches {selection!r}",
        )
    return entries


async def _execute_one(
    adapter: GovernedChaosExecutionAdapter,
    request: ToolCallRequest,
    out_dir: Path,
    measured: list[dict[str, Any]],
) -> dict[str, Any]:
    """Delegate one request to the governed adapter and persist its verdicts.

    Recovery and detection stay separate fields; a run passes only when it
    recovered and its expected signal was validated. A run that produced a
    measured experiment also appends one importable enforce-report record to
    ``measured``; a refused, replayed, or errored run contributes nothing, so
    the report never carries an unmeasured result.
    """

    scenario_id = str(request.arguments["scenario_id"])
    approval_ref = request.metadata.get("approval_ref")
    payload: dict[str, Any] = {
        "scenario_id": scenario_id,
        "mode": Mode.ENFORCE.value,
        "idempotency_key": request.idempotency_key,
        "approval_ref": approval_ref,
        "recovered": False,
        "detected": None,
        "passed": False,
    }
    started = time.monotonic()
    experiment: ExperimentResult | None = None
    try:
        outcome = await adapter.run(request)
    except ToolError as exc:
        payload.update(outcome=f"refused_{exc.kind}", error=str(exc), rollback_succeeded=None)
    except Exception as exc:  # noqa: BLE001 - an unknown adapter state halts the sweep
        payload.update(outcome="adapter_error", error=type(exc).__name__, rollback_succeeded=None)
    else:
        receipt = outcome.receipt
        experiment = outcome.experiment
        payload.update(
            outcome=receipt.outcome.value,
            run_id=receipt.receipt_ref,
            detail=receipt.detail,
            already_existed=receipt.already_existed,
            rollback_succeeded=receipt.rollback_succeeded,
            run_state=outcome.run_state,
            recovered=outcome.recovered,
            experiment_outcome=outcome.experiment_outcome,
            detected=outcome.detected,
            passed=outcome.passed,
        )
    payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
    if experiment is not None and isinstance(approval_ref, str):
        measured.append(
            enforce_report_record(
                experiment,
                approval_ref=approval_ref,
                elapsed_seconds=payload["elapsed_seconds"],
            )
        )
    (out_dir / f"{_slugify(scenario_id)}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[{payload['outcome']}] {scenario_id} recovered={payload['recovered']} "
        f"detected={payload['detected']} passed={payload['passed']} "
        f"elapsed={payload['elapsed_seconds']}s",
        flush=True,
    )
    return payload


def _unsupported_target(entry: CatalogEntry, out_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scenario_id": entry.id,
        "mode": Mode.ENFORCE.value,
        "outcome": "refused_target_type",
        "detail": f"target_type {entry.spec.get('target_type')!r} has no substrate identity",
        "recovered": False,
        "detected": None,
        "passed": False,
        "rollback_succeeded": None,
        "elapsed_seconds": 0.0,
    }
    (out_dir / f"{_slugify(entry.id)}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(f"[refused_target_type] {entry.id}", flush=True)
    return payload


def _refuse(out_dir: Path, refusal: _EnforceRefusalError, *, mode: str = "enforce") -> int:
    payload = {
        "mode": mode,
        "outcome": "refused",
        "reason": refusal.reason,
        "detail": refusal.detail,
        "mutation_attempted": False,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)
    return _REFUSED_EXIT


async def _run_enforce(
    factory: ScenarioFactory,
    *,
    scenario_id: str | None,
    sweep: bool = False,
    limit: int | None,
    measured_report: Path | None = None,
) -> int:
    """Run selected promoted scenarios only through the injected governed adapter."""

    out_dir = _report_dir()
    try:
        bindings = _governed_bindings()
        approval_ref = _approval_claim()
        context = _substrate_context()
        action_type = _chaos_action_type()
        all_entries = load_all()
        promoted = load_promoted()
        entries = _select_entries(
            factory,
            promoted,
            scenario_id=scenario_id,
            sweep=sweep,
            limit=limit,
        )
    except _EnforceRefusalError as refusal:
        return _refuse(out_dir, refusal)
    adapter = GovernedChaosExecutionAdapter(
        entries=all_entries,
        promoted_ids=frozenset(entry.id for entry in promoted),
        factory=factory,
        context=context,
        bindings=bindings,
        action_type=action_type,
        max_hold_seconds=float(os.environ.get("FDAI_MAX_HOLD_SECONDS", "180")),
    )
    fingerprint = catalog_fingerprint(all_entries)
    reports: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if index:
            await asyncio.sleep(_SETTLE_SECONDS)
        targets = approved_catalog_targets(entry, context)
        if targets is None:
            reports.append(_unsupported_target(entry, out_dir))
            continue
        request = catalog_enforce_request(
            entry,
            targets=targets,
            approval_ref=approval_ref,
            fingerprint=fingerprint,
            stop_conditions=tuple(action_type.stop_conditions),
            tier=Tier.T0,
        )
        payload = await _execute_one(adapter, request, out_dir, measured)
        reports.append(payload)
        if payload["outcome"] in {"failed", "adapter_error"} or (
            payload.get("rollback_succeeded") is False
        ):
            print("sweep halted: rollback or recovery is not verified", flush=True)
            break
    (out_dir / "report.json").write_text(json.dumps({"runs": reports}, indent=2, sort_keys=True))
    _write_measured_report(out_dir, measured, measured_report)
    _write_summary(out_dir, reports)
    passed = sum(1 for report in reports if report.get("passed") is True)
    print(f"\nsummary: {passed}/{len(entries)} recovered and detected  ->  {out_dir}", flush=True)
    return 0 if passed == len(entries) else 1


async def _close(*, scenario_id: str, reason: str) -> int:
    """Release a scenario's targets only through an audited, Var-approved closure.

    The closure approval comes from its own variable and is verified as a separate
    closure decision; the adapter refuses the approval that authorized the run's
    injection. Closure is addressed by target, so it also releases a run orphaned
    by a stopped process whose idempotency key can no longer be rebuilt.
    """

    out_dir = _report_dir()
    try:
        bindings = _governed_bindings()
        approval_ref = _approval_claim("FDAI_CHAOS_CLOSURE_APPROVAL_REF")
        context = _substrate_context()
        if not reason.strip() or len(reason) > 512:
            raise _EnforceRefusalError(
                "closure_reason_missing",
                "--closure-reason must state how manual recovery was verified",
            )
        entry = next((item for item in load_all() if item.id == scenario_id), None)
        targets = approved_catalog_targets(entry, context) if entry is not None else None
        if targets is None:
            raise _EnforceRefusalError(
                "closure_target_unknown",
                f"scenario {scenario_id!r} has no substrate target identity",
            )
    except _EnforceRefusalError as refusal:
        return _refuse(out_dir, refusal, mode="closure")
    results = await GovernedChaosClosure(bindings=bindings).close_targets(
        targets=targets,
        approval_ref=approval_ref,
        reason=reason.strip(),
    )
    payload = {
        "mode": "closure",
        "scenario_id": scenario_id,
        "results": [dataclasses.asdict(item) for item in results],
    }
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True), flush=True)
    settled = {"closed", "already_closed", "already_released", "no_claim"}
    return 0 if all(item.reason in settled for item in results) else 1


def _report_dir() -> Path:
    root = Path("logs/catalog-runs") / datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_measured_report(
    out_dir: Path,
    measured: list[dict[str, Any]],
    measured_report: Path | None = None,
) -> None:
    """Write the importable enforce report, or nothing when no run was measured.

    An empty file would be an unmeasured claim, so the report exists only when at
    least one governed run produced an experiment record. ``measured_report``
    pins a second copy where a deployment's evidence projection reads it; its
    parent directory must already exist, because creating an unexpected path
    would hide a misconfigured evidence location.
    """

    if not measured:
        return
    payload = json.dumps({"runs": measured}, indent=2, sort_keys=True) + "\n"
    (out_dir / "enforce-report.json").write_text(payload)
    if measured_report is not None:
        measured_report.write_text(payload)


def _write_summary(out_dir: Path, reports: list[dict[str, Any]]) -> None:
    lines = [
        "# Catalog run summary",
        "",
        f"Report root: `{out_dir}`",
        "",
        "| Scenario | Outcome | Recovered | Detected | Passed | Detail | Elapsed (s) | Error |",
        "|----------|---------|-----------|----------|--------|--------|-------------|-------|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.get('scenario_id')}` | {r.get('outcome')} | {r.get('recovered')} | "
            f"{r.get('detected')} | {r.get('passed')} | {r.get('detail') or ''} | "
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
    grp.add_argument(
        "--run",
        metavar="SCENARIO_ID",
        help="Run one promoted scenario, by catalog id or reference scenario id.",
    )
    grp.add_argument(
        "--run-sweep",
        action="store_true",
        help="Run the reference scenario sweep, in demo order, through the governed adapter.",
    )
    grp.add_argument(
        "--run-all",
        action="store_true",
        help="Run every executable promoted scenario through the governed adapter.",
    )
    grp.add_argument(
        "--close",
        metavar="SCENARIO_ID",
        help="Close the escalated or orphaned run holding this scenario's targets.",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="Cap on --run-all (executes the first N executable entries).",
    )
    p.add_argument(
        "--confirm-enforce",
        action="store_true",
        help="Confirm the operator intends a governed run on the disposable substrate.",
    )
    p.add_argument(
        "--confirm-closure",
        action="store_true",
        help="Confirm manual recovery was verified and a distinct Var approver approved closure.",
    )
    p.add_argument(
        "--closure-reason",
        default="",
        help="How manual recovery was verified; recorded in the audit chain.",
    )
    p.add_argument(
        "--evidence-summary",
        type=Path,
        help="Write a sanitized, fingerprint-bound validation summary.",
    )
    p.add_argument(
        "--measured-report",
        type=Path,
        help="Also write the importable measured enforce report to this exact path.",
    )
    args = p.parse_args(argv)

    factory = default_factory()

    if args.list:
        return _list_command(factory)
    if args.dry_run:
        return asyncio.run(_dry_run(factory, args.evidence_summary))
    if args.close:
        if not args.confirm_closure:
            raise SystemExit("--close requires explicit --confirm-closure")
        return asyncio.run(_close(scenario_id=args.close, reason=args.closure_reason))
    if not args.confirm_enforce:
        raise SystemExit("--run / --run-sweep / --run-all requires explicit --confirm-enforce")
    return asyncio.run(
        _run_enforce(
            factory,
            scenario_id=args.run,
            sweep=args.run_sweep,
            limit=args.limit,
            measured_report=args.measured_report,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
