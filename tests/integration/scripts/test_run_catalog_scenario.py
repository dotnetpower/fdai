"""Regression tests for scripts/catalog/run-catalog-scenario.py."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.guard import ChaosStopEvent, ChaosStopReason
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
)
from fdai.core.chaos.reference_sweep import (
    reference_catalog_id,
    reference_sweep_catalog_ids,
)
from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.run_store import ChaosRunStore
from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.recovery import (
    ProbeVerdict,
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryStrategy,
    compile_recovery_plan,
)
from fdai.delivery.chaos import governed_bindings
from fdai.delivery.chaos.enforce_report import load_enforce_report
from fdai.delivery.chaos.factories import default_factory
from fdai.delivery.chaos.governed_bindings import (
    ChaosApprovalEvidence,
    ChaosRunPlan,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.governed_claims import target_digest
from fdai.delivery.chaos.governed_records import catalog_enforce_request, governed_chaos_run_id
from fdai.delivery.chaos.mutation_scope import (
    ScopedInjector,
    azure_resource_ref,
    kubernetes_pods_ref,
)
from fdai.shared.contracts.models import Mode, Tier
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import ToolCallRequest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "catalog" / "run-catalog-scenario.py"
_MEASURE_SCRIPT_PATH = _REPO_ROOT / "scripts" / "catalog" / "measure-detection-latency.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_catalog_scenario", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_measure_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("measure_detection_latency", _MEASURE_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_builds_every_executable_catalog_entry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    result = asyncio.run(module._dry_run(default_factory()))

    assert result == 0
    output = capsys.readouterr().out
    assert "dry-run: 93/93 entries dispatchable" in output


def test_dry_run_writes_sanitized_fingerprint_bound_summary(tmp_path: Path) -> None:
    module = _load_script()
    summary_path = tmp_path / "summary.json"

    result = asyncio.run(module._dry_run(default_factory(), summary_path))

    assert result == 0
    payload = json.loads(summary_path.read_text())
    outcomes = [entry["outcome"] for entry in payload["entries"]]
    assert payload["evidence_level"] == "dispatchability"
    assert payload["catalog_entry_count"] == 135
    assert outcomes.count("dispatchable") == 93
    assert outcomes.count("skipped_non_executable") == 42


def test_enforce_requires_explicit_confirmation() -> None:
    module = _load_script()

    with pytest.raises(SystemExit, match="requires explicit --confirm-enforce"):
        module.main(["--run", "chaos.chaos-mesh.pod-failure"])


_APPROVAL_REF = "approval:test-run"
_ENV = {
    "FDAI_ENFORCE_SUB_ID": "00000000-0000-0000-0000-000000000000",
    "FDAI_ENFORCE_RG": "rg-test",
    "FDAI_ENFORCE_AKS_CONTEXT": "ctx-test",
    "FDAI_ENFORCE_NS": "workloads",
    "FDAI_ENFORCE_CHAOS_NS": "chaos",
    "FDAI_ENFORCE_BACKEND_DEPLOY": "backend",
    "FDAI_ENFORCE_BACKEND_SVC": "backend",
    "FDAI_ENFORCE_BACKEND_LABEL": "app=backend",
    "FDAI_ENFORCE_VM": "vm-test",
}


_PODS_TARGET = "k8s:ctx-test/workloads/pods/app=backend"
_VM_TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
    "/providers/Microsoft.Compute/virtualMachines/vm-test"
)


def _entry(scenario_id: str, *, target_type: str = "pod") -> CatalogEntry:
    return CatalogEntry(
        id=scenario_id,
        source_path=Path(f"{scenario_id}.yaml"),
        spec={
            "id": scenario_id,
            "version": 1,
            "fault_family": "pod_kill",
            "description": "bounded pod kill",
            "target_type": target_type,
            "expected_signal": "pod_restart",
            "blast_radius_cap": 1,
            "duration_seconds": 0.01,
            "params": {},
            "rollback_note": "restart the pod",
            "injector": "test:pod-kill",
        },
    )


class _Injector:
    fault_type = "pod_kill"

    def __init__(self) -> None:
        self.injected: list[str] = []

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        return None


class _Probe:
    def __init__(self, *, detects: bool) -> None:
        self._detects = detects

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        return self._detects


class _LatencyProbe(_Probe):
    async def first_observed_at(
        self,
        *,
        signal: str,
        targets: Sequence[str],
        window_start: datetime,
        window_end: datetime,
    ) -> datetime | None:
        del signal, targets, window_end
        return window_start + timedelta(milliseconds=1)


class _SpyFactory(ScenarioFactory):
    """Scopes the fake injector exactly like the production factory builders."""

    def __init__(self, injector: _Injector, *, detects: bool = True) -> None:
        super().__init__()
        self.builds: list[str] = []
        self._injector = injector
        self.register_injector("test", self._build_injector)
        self.register_probe("pod_restart", lambda _entry, _context: _Probe(detects=detects))

    def _build_injector(self, entry: CatalogEntry, context: dict[str, Any]) -> ScopedInjector:
        self.builds.append(entry.id)
        if entry.spec["target_type"] == "vm":
            return ScopedInjector(
                self._injector,
                resources=lambda: (
                    azure_resource_ref(
                        context,
                        "Microsoft.Compute/virtualMachines",
                        str(context["vm_name"]),
                    ),
                ),
            )
        return ScopedInjector(self._injector, resources=lambda: (kubernetes_pods_ref(context),))


class _LatencyFactory(_SpyFactory):
    def __init__(self, injector: _Injector) -> None:
        super().__init__(injector)
        self.register_probe("pod_restart", lambda _entry, _context: _LatencyProbe(detects=True))


class _DistributedLock(ResourceLockManager):
    distributed = True


class _Registry:
    def mode_of(self, action_type: str) -> Mode:
        return Mode.ENFORCE

    def record(self, action_type: str) -> None:
        return None


class _Verifier:
    def __init__(self) -> None:
        self.requests: list[ToolCallRequest] = []
        self.closure_requests: list[ToolCallRequest] = []

    async def verify(self, request: ToolCallRequest, *, run_id: str) -> ChaosApprovalEvidence:
        self.requests.append(request)
        return ChaosApprovalEvidence(
            approval_ref=request.metadata.get("approval_ref", _APPROVAL_REF),
            approval_principal="Var",
            approver_ids=("approver-a",),
            initiator_id="initiator-a",
        )

    async def verify_closure(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence:
        self.closure_requests.append(request)
        targets = request.arguments["targets"]
        assert isinstance(targets, list)
        return ChaosApprovalEvidence(
            approval_ref=request.metadata["approval_ref"],
            approval_principal="Var",
            approver_ids=("approver-b",),
            initiator_id="operator-c",
            intent="closure",
            run_id=run_id,
            target_digests=tuple(target_digest(str(item)) for item in targets),
        )


async def _no_stop(_elapsed: float) -> ChaosStopEvent | None:
    return None


async def _stop_now(_elapsed: float) -> ChaosStopEvent | None:
    return ChaosStopEvent(
        run_id="catalog-run",
        impact_envelope_id="impact-1",
        reason=ChaosStopReason.FORBIDDEN_SIGNAL,
        observed_resources=(_PODS_TARGET,),
        observed_signals=("error_budget_burn",),
        occurred_at=datetime.now(tz=UTC),
        detail="forbidden signal observed",
    )


class _Planner:
    def __init__(self, *, guard: Any = _no_stop) -> None:
        self.calls = 0
        self._guard = guard

    async def plan(
        self,
        *,
        run_id: str,
        scenario: FaultScenario,
        targets: tuple[str, ...],
    ) -> ChaosRunPlan:
        self.calls += 1
        now = datetime.now(tz=UTC)
        recovery_plan = compile_recovery_plan(
            strategy=RecoveryStrategy.STATE_FORWARD,
            workflow_ref="recover-service",
            workflow_version="1.0.0",
            catalog_digest="catalog-1",
            actions=(
                RecoveryAction(
                    action_id="restore",
                    action_type_ref="ops.restore-service",
                    action_type_version="1.0.0",
                    target_ref="resource-a",
                    compensation_action_type_ref="ops.undo-restore",
                    stop_conditions=("time_box",),
                    rollback_ref="rollback:restore",
                ),
            ),
            impact_envelope_id="impact-1",
            recovery_objective_ref="rto-1",
            verification_probes=("health",),
            direct_target_ids=("resource-a",),
            graph_revision="graph-1",
            dry_run_receipt="dry-run-1",
            last_rehearsed_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=1),
        )
        return ChaosRunPlan(
            recovery_plan=recovery_plan,
            impact_guard=self._guard,
            causal_hypothesis_ref="hypothesis-1",
            refutation_query_ref="query-1",
            owner_ref="owner-1",
            dry_run_receipt="dry-run-1",
            supported_environment=True,
            maintenance_window_active=True,
            graph_complete=True,
            objective_headroom=True,
            recovery_ready=True,
            telemetry_ready=True,
            no_conflicting_work=True,
            kill_switch_clear=True,
            stop_conditions_ready=True,
            production_or_stateful=False,
        )


class _Dispatcher:
    async def dispatch(self, action: RecoveryAction, *, idempotency_key: str) -> str:
        return f"receipt:{idempotency_key}"


class _Collector:
    def __init__(self, *, complete: bool = True) -> None:
        self._complete = complete

    async def collect(
        self,
        _plan: RecoveryPlanRecord,
    ) -> tuple[tuple[RecoveryProbeResult, ...], bool]:
        kinds = [
            kind
            for kind in RecoveryProbeKind
            if self._complete or kind is not RecoveryProbeKind.RECURRENCE_CLEAR
        ]
        return (
            tuple(
                RecoveryProbeResult(
                    kind=kind,
                    verdict=ProbeVerdict.PASSED,
                    observed_at=datetime.now(tz=UTC),
                    evidence_ref=f"evidence:{kind.value}",
                )
                for kind in kinds
            ),
            True,
        )


def _bindings(
    entries: list[CatalogEntry],
    *,
    store: InMemoryStateStore,
    planner: _Planner | None = None,
    verifier: _Verifier | None = None,
    collector: _Collector | None = None,
) -> GovernedChaosBindings:
    ledger = ScenarioPromotionLedger()
    fingerprint = catalog_fingerprint(entries)
    observed_at = datetime(2026, 9, 16, tzinfo=UTC)
    for entry in entries:
        key = ScenarioEvidenceKey(entry.id, 1, fingerprint)
        common: dict[str, Any] = {"key": key, "observed_at": observed_at, "runner_version": "r/1"}
        ledger.append(
            ScenarioPromotionEvidence(
                evidence_id=f"{entry.id}:shadow",
                from_state=ScenarioPromotionState.COLLECTED,
                to_state=ScenarioPromotionState.SHADOW_VALIDATED,
                actor_principal="Saga",
                audit_ref="audit:shadow",
                stop_condition_observed=True,
                rollback_succeeded=True,
                blast_radius_compliant=True,
                detection_latency_ms=100,
                latency_budget_ms=500,
                **common,
            )
        )
        ledger.append(
            ScenarioPromotionEvidence(
                evidence_id=f"{entry.id}:pending",
                from_state=ScenarioPromotionState.SHADOW_VALIDATED,
                to_state=ScenarioPromotionState.APPROVAL_PENDING,
                actor_principal="Mimir",
                audit_ref="audit:pending",
                **common,
            )
        )
        ledger.append(
            ScenarioPromotionEvidence(
                evidence_id=f"{entry.id}:eligible",
                from_state=ScenarioPromotionState.APPROVAL_PENDING,
                to_state=ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor_principal="Mimir",
                audit_ref="audit:eligible",
                approval_ref="promotion-approval-1",
                approval_principal="Var",
                **common,
            )
        )
    return GovernedChaosBindings(
        state_store=store,
        action_registry=_Registry(),
        scenario_ledger=ledger,
        approval_verifier=verifier or _Verifier(),
        planner=planner or _Planner(),
        recovery_dispatcher=_Dispatcher(),
        evidence_collector=collector or _Collector(),
        target_lock=_DistributedLock(),
    )


def _governed_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entries: list[CatalogEntry],
    bindings: GovernedChaosBindings | None,
    injector: _Injector,
    *,
    detects: bool = True,
) -> tuple[ModuleType, _SpyFactory]:
    module = _load_script()
    monkeypatch.chdir(tmp_path)
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FDAI_ENFORCE_APPROVAL_REF", _APPROVAL_REF)
    monkeypatch.delenv("FDAI_CHAOS_CLOSURE_APPROVAL_REF", raising=False)
    factory = _SpyFactory(injector, detects=detects)
    monkeypatch.setattr(module, "default_factory", lambda: factory)
    monkeypatch.setattr(module, "load_all", lambda: list(entries))
    monkeypatch.setattr(module, "load_promoted", lambda: list(entries))
    if bindings is None:
        monkeypatch.setattr(governed_bindings, "entry_points", lambda *, group: ())
    else:
        monkeypatch.setattr(module, "load_governed_chaos_bindings", lambda _environment: bindings)
    return module, factory


def _report(root: Path) -> dict[str, Any]:
    reports = sorted((root / "logs" / "catalog-runs").glob("*/report.json"))
    payload: dict[str, Any] = json.loads(reports[-1].read_text(encoding="utf-8"))
    return payload


def test_substrate_context_refuses_missing_env_without_file_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FDAI_ENFORCE_VM")

    with pytest.raises(module._EnforceRefusalError, match="FDAI_ENFORCE_VM"):
        module._substrate_context()

    monkeypatch.setenv("FDAI_ENFORCE_VM", "vm-test")
    context = module._substrate_context()
    assert context["workload_label"] == "backend"
    assert "promotion_evidence_path" not in context


def test_live_mode_has_no_raw_harness_mutation_path() -> None:
    tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    def callers(method: str) -> set[str]:
        return {
            function.name
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
        }

    assert {"fdai.core.chaos.harness", "fdai.core.chaos.runner"}.isdisjoint(modules)
    assert {"FaultInjectionHarness", "GovernedChaosRunner"}.isdisjoint(names | attributes)
    assert {"inject", "run_enforce"}.isdisjoint(attributes)
    adapter_calls = {
        (function.name, node.func.attr)
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "adapter"
    }

    assert callers("build") == {"_dry_run"}
    assert adapter_calls == {("_execute_one", "run")}
    assert "GovernedChaosExecutionAdapter" in names


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unbound", "governed_execution_unbound"),
        ("invalid", "governed_execution_invalid"),
        ("no_approval_claim", "approval_claim_missing"),
        ("no_substrate", "substrate_context_missing"),
        ("not_promoted", "no_executable_promoted_scenario"),
    ],
)
def test_enforce_refuses_structurally_before_any_governed_request(
    case: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    store = InMemoryStateStore()
    planner = _Planner()
    bindings = None if case == "unbound" else _bindings(entries, store=store, planner=planner)
    injector = _Injector()
    module, factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)
    if case == "invalid":

        def _broken(_environment: object) -> GovernedChaosBindings:
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(module, "load_governed_chaos_bindings", _broken)
    elif case == "no_approval_claim":
        monkeypatch.delenv("FDAI_ENFORCE_APPROVAL_REF")
    elif case == "no_substrate":
        monkeypatch.delenv("FDAI_ENFORCE_VM")
    elif case == "not_promoted":
        monkeypatch.setattr(module, "load_promoted", lambda: [])

    result = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])

    report = _report(tmp_path)
    assert result == 3
    assert report["outcome"] == "refused"
    assert report["reason"] == reason
    assert report["mutation_attempted"] is False
    assert planner.calls == 0
    assert factory.builds == []
    assert injector.injected == []
    assert list(store.audit_entries) == []


def test_measure_detection_latency_refuses_unbound_before_substrate_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_measure_script()
    runner = module._load_catalog_runner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_governed_chaos_bindings", lambda _environment: None)

    def _unexpected_substrate() -> dict[str, Any]:
        raise AssertionError("substrate context must not be read before binding")

    monkeypatch.setattr(runner, "_substrate_context", _unexpected_substrate)

    result = module.main(["--scenario", "chaos.test.pod-kill", "--confirm-enforce"])

    stderr = capsys.readouterr().err
    payload = json.loads(stderr)
    assert result == 3
    assert payload["outcome"] == "refused"
    assert payload["reason"] == "governed_execution_unbound"
    assert payload["mutation_attempted"] is False


def test_measure_detection_latency_prints_governed_latency_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_measure_script()
    runner = module._load_catalog_runner()
    monkeypatch.chdir(tmp_path)
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FDAI_ENFORCE_APPROVAL_REF", _APPROVAL_REF)
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    monkeypatch.setattr(runner, "default_factory", lambda: _LatencyFactory(injector))
    monkeypatch.setattr(runner, "load_all", lambda: list(entries))
    monkeypatch.setattr(runner, "load_promoted", lambda: list(entries))
    monkeypatch.setattr(runner, "load_governed_chaos_bindings", lambda _environment: bindings)

    result = module.main(["--scenario", "chaos.test.pod-kill", "--confirm-enforce"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["driver"] == "measure-detection-latency"
    assert payload["scenario"] == "chaos.test.pod-kill"
    assert payload["outcome"] == "succeeded"
    assert payload["detected"] is True
    assert payload["detection_latency_seconds"] == 0.001
    assert injector.injected == [_PODS_TARGET]


def test_enforce_delegates_to_governed_adapter_and_replays_duplicate_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    verifier = _Verifier()
    bindings = _bindings(entries, store=InMemoryStateStore(), verifier=verifier)
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    first = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])
    first_run = _report(tmp_path)["runs"][0]
    second = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])
    second_run = _report(tmp_path)["runs"][0]

    assert (first, second) == (0, 0)
    assert first_run["outcome"] == "succeeded"
    assert first_run["detail"] == "recovered:validated"
    assert (first_run["recovered"], first_run["detected"], first_run["passed"]) == (
        True,
        True,
        True,
    )
    assert second_run["outcome"] == "already_applied"
    assert second_run["run_id"] == first_run["run_id"]
    assert (second_run["detected"], second_run["passed"]) == (True, True)
    assert injector.injected == [_PODS_TARGET]
    assert len(verifier.requests) == 1
    request = verifier.requests[0]
    assert request.mode is Mode.ENFORCE
    assert request.action_type_name == "tool.run-chaos-experiment"
    assert request.arguments["targets"] == [_PODS_TARGET]
    assert request.metadata["approval_ref"] == _APPROVAL_REF
    assert request.metadata["tier"] == "t0"
    assert [item.seconds for item in request.stop_conditions] == [600]


def test_reference_scenario_id_selects_its_reviewed_catalog_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog_id = reference_catalog_id("aks-pod-kill")
    assert catalog_id is not None
    entries = [_entry(catalog_id), _entry("chaos.test.other")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run", "aks-pod-kill", "--confirm-enforce"])

    runs = _report(tmp_path)["runs"]
    assert result == 0
    assert [run["scenario_id"] for run in runs] == [catalog_id]


def test_run_sweep_executes_the_reference_scenarios_in_demo_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sweep_ids = reference_sweep_catalog_ids()
    selected = (sweep_ids[2], sweep_ids[0])
    entries = [_entry("chaos.test.unmapped"), *(_entry(item) for item in selected)]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run-sweep", "--confirm-enforce"])

    runs = _report(tmp_path)["runs"]
    assert result == 0
    assert [run["scenario_id"] for run in runs] == [sweep_ids[0], sweep_ids[2]]


def test_run_sweep_refuses_when_no_reference_scenario_is_promoted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run-sweep", "--confirm-enforce"])

    report = _report(tmp_path)
    assert result == 3
    assert report["reason"] == "no_executable_promoted_scenario"
    assert "--run-sweep" in report["detail"]
    assert injector.injected == []


def test_measured_runs_write_an_importable_enforce_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])

    measured = sorted((tmp_path / "logs" / "catalog-runs").glob("*/enforce-report.json"))
    assert result == 0
    signals = load_enforce_report(measured[-1])
    assert len(signals) == 1
    assert signals[0].metadata["approval_ref"] == _APPROVAL_REF


def test_measured_report_is_pinned_where_a_deployment_reads_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)
    pinned = tmp_path / "evidence" / "report.json"
    pinned.parent.mkdir()

    result = module.main(
        ["--run", "chaos.test.pod-kill", "--confirm-enforce", "--measured-report", str(pinned)]
    )

    assert result == 0
    signals = load_enforce_report(pinned)
    assert len(signals) == 1
    run = json.loads(pinned.read_text(encoding="utf-8"))["runs"][0]
    assert run["outcome"] == "validated"
    assert (run["detected"], run["reverted"]) == (True, True)


def test_a_refused_run_pins_no_measured_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill", target_type="db")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)
    pinned = tmp_path / "evidence" / "report.json"
    pinned.parent.mkdir()

    result = module.main(
        ["--run", "chaos.test.pod-kill", "--confirm-enforce", "--measured-report", str(pinned)]
    )

    assert result == 1
    assert not pinned.exists()


def test_a_refused_run_writes_no_measured_enforce_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill", target_type="db")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])

    runs = _report(tmp_path)["runs"]
    assert result == 1
    assert runs[0]["outcome"] == "refused_target_type"
    assert list((tmp_path / "logs" / "catalog-runs").glob("*/enforce-report.json")) == []
    assert injector.injected == []


def test_run_all_halts_sweep_after_unverified_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.a"), _entry("chaos.test.b")]
    bindings = _bindings(entries, store=InMemoryStateStore(), collector=_Collector(complete=False))
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run-all", "--confirm-enforce"])

    runs = _report(tmp_path)["runs"]
    assert result == 1
    assert [run["scenario_id"] for run in runs] == ["chaos.test.a"]
    assert runs[0]["outcome"] == "failed"
    assert runs[0]["rollback_succeeded"] is False
    assert runs[0]["passed"] is False
    assert injector.injected == [_PODS_TARGET]


async def _seed_observing(store: InMemoryStateStore, run_id: str) -> None:
    run_store = ChaosRunStore(state_store=store)
    snapshot = await run_store.create(run_id=run_id, at=datetime.now(tz=UTC))
    for state in (
        ChaosRunState.IMPACT_CHECKED,
        ChaosRunState.DRY_RUN_VERIFIED,
        ChaosRunState.APPROVED,
        ChaosRunState.INJECTING,
        ChaosRunState.OBSERVING,
    ):
        snapshot = await run_store.transition(
            snapshot,
            target=state,
            idempotency_key=f"{run_id}:{state.value}",
            at=datetime.now(tz=UTC),
        )


@pytest.mark.parametrize(
    ("case", "injected", "detail"),
    [
        ("forced_stop", [_PODS_TARGET], "stopped:forbidden_signal:recovered"),
        ("restart", [], "resumed:recovered"),
    ],
)
def test_enforce_stop_and_restart_end_in_verified_recovery(
    case: str,
    injected: list[str],
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    store = InMemoryStateStore()
    planner = _Planner(guard=_stop_now if case == "forced_stop" else _no_stop)
    bindings = _bindings(entries, store=store, planner=planner)
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)
    if case == "restart":
        request = catalog_enforce_request(
            entries[0],
            targets=(_PODS_TARGET,),
            approval_ref=_APPROVAL_REF,
            fingerprint=catalog_fingerprint(entries),
            stop_conditions=(),
            tier=Tier.T0,
        )
        run_id = governed_chaos_run_id(request.idempotency_key, entries[0].id, (_PODS_TARGET,))
        asyncio.run(_seed_observing(store, run_id))

    result = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])

    run = _report(tmp_path)["runs"][0]
    assert result == 1
    assert run["outcome"] == "stopped"
    assert run["rollback_succeeded"] is True
    assert run["detail"] == detail
    assert injector.injected == injected


def test_enforce_reports_a_recovered_detection_gap_as_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    injector = _Injector()
    module, _factory = _governed_cli(
        monkeypatch, tmp_path, entries, bindings, injector, detects=False
    )

    result = module.main(["--run", "chaos.test.pod-kill", "--confirm-enforce"])

    run = _report(tmp_path)["runs"][0]
    summary = (next((tmp_path / "logs" / "catalog-runs").glob("*/summary.md"))).read_text(
        encoding="utf-8"
    )
    assert result == 1
    assert run["outcome"] == "succeeded"
    assert run["detail"] == "recovered:not_detected"
    assert (run["recovered"], run["detected"], run["passed"]) == (True, False, False)
    assert run["experiment_outcome"] == "not_detected"
    assert "| Detected |" in summary


def test_enforce_binds_vm_scenarios_to_the_vm_resource_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.vm-stop", target_type="vm")]
    verifier = _Verifier()
    bindings = _bindings(entries, store=InMemoryStateStore(), verifier=verifier)
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run", "chaos.test.vm-stop", "--confirm-enforce"])

    assert result == 0
    assert injector.injected == [_VM_TARGET]
    assert verifier.requests[0].arguments["targets"] == [_VM_TARGET]


def test_enforce_refuses_target_types_without_a_substrate_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.lb-scale", target_type="lb")]
    planner = _Planner()
    bindings = _bindings(entries, store=InMemoryStateStore(), planner=planner)
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)

    result = module.main(["--run", "chaos.test.lb-scale", "--confirm-enforce"])

    run = _report(tmp_path)["runs"][0]
    assert result == 1
    assert run["outcome"] == "refused_target_type"
    assert run["passed"] is False
    assert planner.calls == 0
    assert injector.injected == []


def test_close_releases_an_escalated_target_through_an_audited_var_closure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    store = InMemoryStateStore()
    verifier = _Verifier()
    bindings = _bindings(
        entries, store=store, verifier=verifier, collector=_Collector(complete=False)
    )
    injector = _Injector()
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, injector)
    run = ["--run", "chaos.test.pod-kill", "--confirm-enforce"]
    close = ["--close", "chaos.test.pod-kill", "--confirm-closure"]

    reason = ["--closure-reason", "fault absent; workload healthy"]

    escalated = module.main(run)
    monkeypatch.setenv("FDAI_ENFORCE_APPROVAL_REF", "approval:next-run")
    blocked = module.main(run)
    blocked_run = _report(tmp_path)["runs"][0]
    monkeypatch.setenv("FDAI_CHAOS_CLOSURE_APPROVAL_REF", _APPROVAL_REF)
    reused = module.main([*close, *reason])
    reused_closure = _report(tmp_path)
    monkeypatch.setenv("FDAI_CHAOS_CLOSURE_APPROVAL_REF", "approval:closure")
    closed = module.main([*close, *reason])
    closure = _report(tmp_path)

    assert (escalated, blocked, reused, closed) == (1, 1, 1, 0)
    assert "conflicting_work_open" in blocked_run["detail"]
    assert [item["reason"] for item in reused_closure["results"]] == [
        "closure_reuses_enforce_approval"
    ]
    assert [item["reason"] for item in closure["results"]] == ["closed"]
    assert len(verifier.closure_requests) == 1
    closure_request = verifier.closure_requests[0]
    assert closure_request.metadata["intent"] == "closure"
    assert closure_request.metadata["approval_ref"] == "approval:closure"
    assert closure_request.arguments["targets"] == [_PODS_TARGET]
    assert "chaos.run.closure" in [item["entry"]["action_kind"] for item in store.audit_entries]
    assert injector.injected == [_PODS_TARGET]


def test_close_requires_confirmation_and_a_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = [_entry("chaos.test.pod-kill")]
    bindings = _bindings(entries, store=InMemoryStateStore())
    module, _factory = _governed_cli(monkeypatch, tmp_path, entries, bindings, _Injector())

    with pytest.raises(SystemExit, match="--confirm-closure"):
        module.main(["--close", "chaos.test.pod-kill"])
    unapproved = module.main(["--close", "chaos.test.pod-kill", "--confirm-closure"])
    unapproved_report = _report(tmp_path)
    monkeypatch.setenv("FDAI_CHAOS_CLOSURE_APPROVAL_REF", "approval:closure")
    unexplained = module.main(["--close", "chaos.test.pod-kill", "--confirm-closure"])

    report = _report(tmp_path)
    assert (unapproved, unexplained) == (3, 3)
    assert unapproved_report["reason"] == "approval_claim_missing"
    assert "FDAI_CHAOS_CLOSURE_APPROVAL_REF" in unapproved_report["detail"]
    assert (report["mode"], report["reason"]) == ("closure", "closure_reason_missing")
