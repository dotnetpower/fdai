"""Policy-aware Azure Genesis orchestration regressions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPT_DIR))

import genesis_orchestrator as orchestrator  # noqa: E402
import genesis_private_execution as private_execution  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_checks import CheckError, GenesisChecks  # noqa: E402
from genesis_foundation import FoundationPlanError, FoundationPlanInputs  # noqa: E402
from genesis_status import (  # noqa: E402
    PRIVATE_FOUNDATION_STAGES,
    StatusStore,
    StatusStoreError,
    render_plan,
)
from resource_provider_reconcile import (  # noqa: E402
    APPLICATION_PROVIDERS,
    FOUNDATION_PROVIDERS,
    ProviderReconcileError,
    reconcile_resource_providers,
)

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TENANT = "00000000-0000-0000-0000-000000000002"
_GENESIS_PYTHON = (
    _SCRIPT_DIR / "genesis_bastion.py",
    _SCRIPT_DIR / "genesis_orchestrator.py",
    _SCRIPT_DIR / "genesis_approval.py",
    _SCRIPT_DIR / "genesis_checks.py",
    _SCRIPT_DIR / "genesis_foundation_apply.py",
    _SCRIPT_DIR / "genesis_foundation_apply_contract.py",
    _SCRIPT_DIR / "genesis_foundation_state.py",
    _SCRIPT_DIR / "genesis_foundation_state_archive.py",
    _SCRIPT_DIR / "genesis_foundation_state_contract.py",
    _SCRIPT_DIR / "genesis_foundation.py",
    _SCRIPT_DIR / "genesis_private_command.py",
    _SCRIPT_DIR / "genesis_private_errors.py",
    _SCRIPT_DIR / "genesis_private_execution.py",
    _SCRIPT_DIR / "genesis_runner_image.py",
    _SCRIPT_DIR / "genesis_runner_image_contract.py",
    _SCRIPT_DIR / "genesis_runner_enrollment.py",
    _SCRIPT_DIR / "genesis_status.py",
    _SCRIPT_DIR / "genesis_subprocess.py",
    _SCRIPT_DIR / "resource_provider_reconcile.py",
)


class ProviderRunner:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, arguments: tuple[str, ...], _timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        namespace = arguments[arguments.index("--namespace") + 1]
        if arguments[:2] == ("provider", "show"):
            return subprocess.CompletedProcess(arguments, 0, self.states[namespace] + "\n", "")
        if arguments[:2] == ("provider", "register"):
            self.states[namespace] = "Registered"
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(arguments)


def test_genesis_python_entrypoint_remains_python_310_compatible() -> None:
    python = shutil.which("python3")
    assert python is not None
    for path in _GENESIS_PYTHON:
        result = subprocess.run(  # noqa: S603 - fixed local interpreter and source paths
            [python, "-m", "py_compile", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "from datetime import UTC" not in path.read_text(encoding="utf-8")


def test_complete_provider_profile_covers_the_baseline_routes_only() -> None:
    expected = {
        "Microsoft.App",
        "Microsoft.Authorization",
        "Microsoft.CognitiveServices",
        "Microsoft.Compute",
        "Microsoft.ContainerRegistry",
        "Microsoft.DBforPostgreSQL",
        "Microsoft.DevTestLab",
        "Microsoft.EventGrid",
        "Microsoft.EventHub",
        "Microsoft.Insights",
        "Microsoft.KeyVault",
        "Microsoft.ManagedIdentity",
        "Microsoft.Network",
        "Microsoft.OperationalInsights",
        "Microsoft.Resources",
        "Microsoft.Storage",
    }

    assert expected == set((*FOUNDATION_PROVIDERS, *APPLICATION_PROVIDERS))
    assert len(expected) == 16
    assert {
        "Microsoft.ApiManagement",
        "Microsoft.BotService",
        "Microsoft.Communication",
        "Microsoft.Consumption",
        "Microsoft.ContainerService",
        "Microsoft.DBforMySQL",
        "Microsoft.Web",
    }.isdisjoint(expected)


def test_provider_preview_reports_every_missing_namespace_without_mutation() -> None:
    required = tuple(dict.fromkeys((*FOUNDATION_PROVIDERS, *APPLICATION_PROVIDERS)))
    states = {namespace: "Registered" for namespace in required}
    states["Microsoft.App"] = "NotRegistered"
    states["Microsoft.Compute"] = "NotRegistered"
    runner = ProviderRunner(states)

    report = reconcile_resource_providers(
        subscription_id=_SUBSCRIPTION,
        profile="complete",
        apply=False,
        run=runner,
    )

    assert report.state == "review"
    assert report.missing == ("Microsoft.Compute", "Microsoft.App")
    assert report.mutation_performed is False
    assert not any(call[:2] == ("provider", "register") for call in runner.calls)


def test_provider_apply_registers_only_missing_namespaces_and_reads_them_back() -> None:
    required = tuple(dict.fromkeys((*FOUNDATION_PROVIDERS, *APPLICATION_PROVIDERS)))
    states = {namespace: "Registered" for namespace in required}
    states["Microsoft.Network"] = "NotRegistered"
    states["Microsoft.KeyVault"] = "Unregistered"
    runner = ProviderRunner(states)
    progress: list[tuple[str, int, int]] = []

    report = reconcile_resource_providers(
        subscription_id=_SUBSCRIPTION,
        profile="complete",
        apply=True,
        run=runner,
        poll_seconds=0.01,
        sleep=lambda _seconds: None,
        progress=lambda name, done, total: progress.append((name, done, total)),
    )

    register_calls = [call for call in runner.calls if call[:2] == ("provider", "register")]
    assert {call[call.index("--namespace") + 1] for call in register_calls} == {
        "Microsoft.Network",
        "Microsoft.KeyVault",
    }
    assert all("--wait" not in call for call in register_calls)
    assert report.state == "ready"
    assert report.requested == ("Microsoft.Network", "Microsoft.KeyVault")
    assert report.mutation_performed is True
    assert progress[-1] == ("readback", len(required), len(required))


def test_provider_apply_rejects_an_indeterminate_state() -> None:
    states = {namespace: "Registered" for namespace in FOUNDATION_PROVIDERS}
    states["Microsoft.Compute"] = "Mystery"

    with pytest.raises(ProviderReconcileError, match="indeterminate"):
        reconcile_resource_providers(
            subscription_id=_SUBSCRIPTION,
            profile="foundation",
            apply=True,
            run=ProviderRunner(states),
        )


def test_provider_preview_rejects_an_indeterminate_state() -> None:
    states = {namespace: "Registered" for namespace in FOUNDATION_PROVIDERS}
    states["Microsoft.Compute"] = "Mystery"

    with pytest.raises(ProviderReconcileError, match="indeterminate"):
        reconcile_resource_providers(
            subscription_id=_SUBSCRIPTION,
            profile="foundation",
            apply=False,
            run=ProviderRunner(states),
        )


def test_provider_inspection_runs_with_bounded_parallelism() -> None:
    required = tuple(dict.fromkeys((*FOUNDATION_PROVIDERS, *APPLICATION_PROVIDERS)))
    active = 0
    maximum_active = 0
    lock = threading.Lock()
    calls: list[float] = []

    def run(arguments: tuple[str, ...], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        nonlocal active, maximum_active
        calls.append(timeout_seconds)
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return subprocess.CompletedProcess(arguments, 0, "Registered\n", "")

    report = reconcile_resource_providers(
        subscription_id=_SUBSCRIPTION,
        profile="complete",
        apply=False,
        run=run,
        timeout_seconds=30,
    )

    assert report.state == "ready"
    assert len(calls) == len(required)
    assert maximum_active > 1
    assert all(0 < timeout <= 30 for timeout in calls)


def test_provider_registration_requests_run_concurrently() -> None:
    states = {namespace: "Registered" for namespace in FOUNDATION_PROVIDERS}
    missing = ("Microsoft.Compute", "Microsoft.Network", "Microsoft.Storage")
    for namespace in missing:
        states[namespace] = "NotRegistered"
    barrier = threading.Barrier(len(missing))

    class ConcurrentRegistrationRunner(ProviderRunner):
        def __call__(
            self, arguments: tuple[str, ...], timeout_seconds: float
        ) -> subprocess.CompletedProcess[str]:
            if arguments[:2] == ("provider", "register"):
                namespace = arguments[arguments.index("--namespace") + 1]
                self.calls.append(arguments)
                barrier.wait(timeout=1)
                self.states[namespace] = "Registered"
                return subprocess.CompletedProcess(arguments, 0, "", "")
            return super().__call__(arguments, timeout_seconds)

    report = reconcile_resource_providers(
        subscription_id=_SUBSCRIPTION,
        profile="foundation",
        apply=True,
        run=ConcurrentRegistrationRunner(states),
        poll_seconds=0.01,
        sleep=lambda _seconds: None,
    )

    assert report.requested == missing


def test_failed_provider_registration_conservatively_records_mutation() -> None:
    states = {namespace: "Registered" for namespace in FOUNDATION_PROVIDERS}
    states["Microsoft.Compute"] = "NotRegistered"

    class FailedRegistrationRunner(ProviderRunner):
        def __call__(
            self, arguments: tuple[str, ...], timeout_seconds: float
        ) -> subprocess.CompletedProcess[str]:
            if arguments[:2] == ("provider", "register"):
                self.calls.append(arguments)
                return subprocess.CompletedProcess(arguments, 1, "", "denied")
            return super().__call__(arguments, timeout_seconds)

    with pytest.raises(ProviderReconcileError) as raised:
        reconcile_resource_providers(
            subscription_id=_SUBSCRIPTION,
            profile="foundation",
            apply=True,
            run=FailedRegistrationRunner(states),
        )

    assert raised.value.mutation_performed is True


def test_status_is_private_identifier_free_and_reports_exact_remaining_work(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "status"
    work_dir.mkdir(mode=0o700)
    store = StatusStore(
        path=work_dir / "status.json",
        source_commit="a" * 40,
        target_binding="b" * 64,
        mode="inspect",
        deadline_at="2999-09-10T12:00:00Z",
    )

    store.update(stage="toolchain", state="running", completed=True)
    store.update(stage="target", state="waiting", reason_code="review_required")

    payload = json.loads((work_dir / "status.json").read_text(encoding="utf-8"))
    assert payload["progress_percent"] == 6
    assert payload["stages_completed"] == 1
    assert payload["stages_total"] == 15
    assert payload["stages_skipped"] == 0
    assert payload["remaining_stages"][0] == "target"
    assert payload["subscription_ready"] is False
    assert (work_dir / "status.json").stat().st_mode & 0o777 == 0o600
    serialized = json.dumps(payload)
    assert _SUBSCRIPTION not in serialized
    assert _TENANT not in serialized


def test_procedure_banner_numbers_every_stage_and_explains_both_routes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_plan("apply")

    output = capsys.readouterr().err
    assert "Mode: mutation-enabled preflight; prompts: none" in output
    assert "1. Toolchain prerequisites" in output
    assert "15. Post-deployment verification" in output
    assert "public-dev -> preview and exact-plan wait" in output
    assert "private-runner -> image, Foundation, enrollment, and state checkpoints" in output
    assert "no route fallback, unsealed apply, or readiness claim" in output


def test_status_rejects_symlinked_or_permissive_work_directories(tmp_path: Path) -> None:
    private_target = tmp_path / "private-target"
    private_target.mkdir(mode=0o700)
    symlink = tmp_path / "linked-status"
    symlink.symlink_to(private_target, target_is_directory=True)
    permissive = tmp_path / "permissive-status"
    permissive.mkdir(mode=0o755)
    permissive.chmod(0o755)

    for work_dir in (symlink, permissive):
        with pytest.raises(StatusStoreError, match="unsafe_orchestration_work_dir"):
            StatusStore(
                path=work_dir / "status.json",
                source_commit="a" * 40,
                target_binding="b" * 64,
                mode="inspect",
                deadline_at="2999-09-10T12:00:00Z",
            )


def test_status_preserves_an_incomplete_policy_probe_binding_across_retry(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "status"
    work_dir.mkdir(mode=0o700)
    first = StatusStore(
        path=work_dir / "status.json",
        source_commit="a" * 40,
        target_binding="b" * 64,
        mode="apply",
        deadline_at="2000-09-10T12:00:00Z",
    )
    first.policy_report = {
        "schema_version": "fdai.azure-policy-route.v1",
        "state": "probing",
        "route": "incomplete",
        "cleanup_complete": False,
        "probe_binding": "c" * 16,
    }
    first.mutation_performed = True
    first.update(stage="policy", state="failed")

    retry = StatusStore(
        path=work_dir / "status.json",
        source_commit="a" * 40,
        target_binding="b" * 64,
        mode="apply",
        deadline_at="2999-09-10T13:00:00Z",
    )

    assert retry.policy_report == first.policy_report
    assert retry.mutation_performed is True
    assert retry.attempt == 2
    assert retry.deadline_at == "2999-09-10T13:00:00Z"


def test_status_preserves_private_checkpoint_references_after_deadline(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "status"
    work_dir.mkdir(mode=0o700)
    first = StatusStore(
        path=work_dir / "status.json",
        source_commit="a" * 40,
        target_binding="b" * 64,
        mode="apply",
        deadline_at="2000-09-10T12:00:00Z",
    )
    first.route = "private-runner"
    first.foundation_report = {
        "schema_version": "fdai.genesis-private-foundation.v1",
        "state": "waiting",
        "current_checkpoint": "foundation-apply",
        "foundation_plan": {"plan_ref": "foundation-plan-attempt-1"},
        "subscription_ready": False,
    }
    first.update(stage="foundation-apply", state="waiting")

    retry = StatusStore(
        path=work_dir / "status.json",
        source_commit="a" * 40,
        target_binding="b" * 64,
        mode="apply",
        deadline_at="2999-09-10T13:00:00Z",
    )

    assert retry.foundation_report == first.foundation_report
    assert retry.attempt == 2
    assert retry.deadline_at == "2999-09-10T13:00:00Z"


def test_source_gate_uses_the_latest_exact_required_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = GenesisChecks(_ROOT)
    api_paths: list[str] = []
    check_runs = {
        "check_runs": [
            {
                "id": 10,
                "name": "required",
                "head_sha": "a" * 40,
                "app": {"slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 11,
                "name": "required",
                "head_sha": "a" * 40,
                "app": {"slug": "github-actions"},
                "status": "in_progress",
                "conclusion": None,
            },
        ]
    }

    def capture(arguments: tuple[str, ...], _reason: str, *, strip: bool = True) -> str:
        if arguments[:2] == ("/usr/bin/git", "status"):
            return ""
        if arguments[:3] == ("/usr/bin/git", "remote", "get-url"):
            return "https://github.com/example/repository.git"
        api_paths.append(arguments[-1])
        value = json.dumps(check_runs)
        return value.strip() if strip else value

    monkeypatch.setattr(checks, "capture", capture)

    with pytest.raises(CheckError, match="required_ci_not_green"):
        checks.verify_source(
            source_commit="a" * 40,
            repository="example/repository",
            apply=True,
        )

    check_runs["check_runs"][1].update(status="completed", conclusion="success")
    checks.verify_source(
        source_commit="a" * 40,
        repository="example/repository",
        apply=True,
    )
    assert all("check_name=required&filter=latest" in path for path in api_paths)
    check_runs["check_runs"][1]["app"] = {"slug": "untrusted-check-app"}
    with pytest.raises(CheckError, match="required_ci_not_green"):
        checks.verify_source(
            source_commit="a" * 40,
            repository="example/repository",
            apply=True,
        )


def test_target_gate_reads_exact_subscription_region_without_active_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = GenesisChecks(_ROOT)
    calls: list[tuple[str, ...]] = []

    def capture(arguments: tuple[str, ...], reason: str, **_kwargs: object) -> str:
        calls.append(arguments)
        if reason == "azure_context_mismatch":
            return json.dumps({"id": _SUBSCRIPTION, "tenantId": _TENANT})
        if reason == "azure_region_unavailable":
            return "koreacentral"
        raise AssertionError(arguments)

    monkeypatch.setattr(checks, "capture", capture)

    checks.verify_target(
        subscription_id=_SUBSCRIPTION,
        tenant_id=_TENANT,
        region="koreacentral",
    )

    region_call = calls[1]
    assert region_call[1:4] == ("rest", "--method", "get")
    assert f"/subscriptions/{_SUBSCRIPTION}/locations?" in region_call[5]
    assert "list-locations" not in region_call
    assert "account set" not in " ".join(region_call)


def test_target_gate_rejects_region_absent_from_exact_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = GenesisChecks(_ROOT)

    def capture(_arguments: tuple[str, ...], reason: str, **_kwargs: object) -> str:
        if reason == "azure_context_mismatch":
            return json.dumps({"id": _SUBSCRIPTION, "tenantId": _TENANT})
        return ""

    monkeypatch.setattr(checks, "capture", capture)

    with pytest.raises(CheckError, match="azure_region_unavailable"):
        checks.verify_target(
            subscription_id=_SUBSCRIPTION,
            tenant_id=_TENANT,
            region="koreacentral",
        )


def test_source_gate_rejects_required_ci_from_another_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = GenesisChecks(_ROOT)

    def capture(arguments: tuple[str, ...], _reason: str, *, strip: bool = True) -> str:
        del strip
        if arguments[:2] == ("/usr/bin/git", "status"):
            return ""
        if arguments[:3] == ("/usr/bin/git", "remote", "get-url"):
            return "git@github.com:example/repository.git"
        raise AssertionError(arguments)

    monkeypatch.setattr(checks, "capture", capture)

    with pytest.raises(CheckError, match="repository_context_mismatch"):
        checks.verify_source(
            source_commit="a" * 40,
            repository="example/other",
            apply=True,
        )


def _config(tmp_path: Path) -> orchestrator.RunConfig:
    return orchestrator.RunConfig(
        repository_root=_ROOT,
        subscription_id=_SUBSCRIPTION,
        tenant_id=_TENANT,
        region="koreacentral",
        environment="dev",
        repository="example/repository",
        apply=True,
        allow_probe_resources=True,
        provider_timeout_seconds=60,
        execution_timeout_seconds=3600,
        output="json",
        work_dir=tmp_path / "run",
        foundation_inputs=None,
    )


def test_apply_requires_the_full_policy_cleanup_deadline(tmp_path: Path) -> None:
    with pytest.raises(orchestrator.OrchestrationError, match="apply_execution_timeout_too_short"):
        replace(_config(tmp_path), execution_timeout_seconds=1799).validate()


def test_local_private_approval_is_dev_only(tmp_path: Path) -> None:
    approval = tmp_path / "approval.json"

    with pytest.raises(
        orchestrator.OrchestrationError,
        match="local_private_approval_supports_dev_only",
    ):
        replace(
            _config(tmp_path),
            environment="staging",
            approval_file=approval,
        ).validate()


def _foundation_inputs(
    tmp_path: Path, *, environment: str = "dev", quorum: int = 1
) -> FoundationPlanInputs:
    profile = tmp_path / "profile.json"
    write_profile(
        profile,
        ProvisionProfile(
            environment=environment,
            region="koreacentral",
            target_binding=compute_target_binding(
                tenant_id=_TENANT,
                subscription_id=_SUBSCRIPTION,
            ),
            connectivity="online",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=quorum,
            monthly_cost_ceiling=500,
        ),
    )
    return FoundationPlanInputs(
        offline_kit=tmp_path / "kit",
        release_root=tmp_path / "release.pem",
        bundle_public_key=tmp_path / "bundle.pem",
        profile=profile,
        variables_file=tmp_path / "variables.json",
    )


def test_foundation_profile_must_match_the_router_environment(tmp_path: Path) -> None:
    inputs = _foundation_inputs(tmp_path, environment="prod")

    with pytest.raises(
        orchestrator.OrchestrationError,
        match="foundation_profile_context_mismatch",
    ):
        replace(_config(tmp_path), foundation_inputs=inputs).validate()


def test_local_private_approval_cannot_bypass_profile_quorum(tmp_path: Path) -> None:
    inputs = _foundation_inputs(tmp_path, quorum=2)

    with pytest.raises(
        orchestrator.OrchestrationError,
        match="local_private_approval_cannot_satisfy_profile",
    ):
        replace(
            _config(tmp_path),
            foundation_inputs=inputs,
            approval_file=tmp_path / "approval.json",
        ).validate()


def _new_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: orchestrator.RunConfig | None = None,
) -> orchestrator.GenesisOrchestrator:
    monkeypatch.setattr(
        orchestrator.GenesisChecks,
        "capture",
        lambda _self, _arguments, _reason, **_kwargs: "a" * 40,
    )
    instance = orchestrator.GenesisOrchestrator(config or _config(tmp_path))
    monkeypatch.setattr(instance, "_acquire_lock", lambda: None)
    monkeypatch.setattr(instance, "_verify_toolchain", lambda: None)
    monkeypatch.setattr(instance, "_verify_target", lambda: None)
    monkeypatch.setattr(instance, "_verify_source", lambda: None)
    monkeypatch.setattr(instance.checks, "verify_checkout_unchanged", lambda: None)
    return instance


def test_mutation_enabled_toolchain_prepares_access_tools_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        instance.checks,
        "verify_toolchain",
        lambda *, apply: calls.append(("verify", apply)),
    )

    def run_required(
        arguments: tuple[str, ...],
        reason: str,
        *,
        timeout: int,
        capture: bool = False,
        **_kwargs: object,
    ) -> None:
        calls.append(("run", (arguments, reason, timeout, capture)))

    monkeypatch.setattr(instance.checks, "run_required", run_required)

    orchestrator.GenesisOrchestrator._verify_toolchain(instance)

    assert calls[0] == ("verify", True)
    arguments, reason, timeout, capture = calls[1][1]
    assert arguments == (
        "/usr/bin/bash",
        str(_ROOT / "scripts/deployment/azure/prepare-genesis-access-tools.sh"),
    )
    assert reason == "azure_access_tool_preparation_failed"
    assert timeout == 600
    assert capture is True


def test_inspection_toolchain_does_not_change_access_tool_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        _config(tmp_path),
        apply=False,
        repository=None,
        allow_probe_resources=False,
    )
    instance = _new_orchestrator(tmp_path, monkeypatch, config=config)
    calls: list[bool] = []
    monkeypatch.setattr(
        instance.checks,
        "verify_toolchain",
        lambda *, apply: calls.append(apply),
    )
    monkeypatch.setattr(
        instance.checks,
        "run_required",
        lambda *_args, **_kwargs: pytest.fail("inspection changed access-tool configuration"),
    )

    orchestrator.GenesisOrchestrator._verify_toolchain(instance)

    assert calls == [False]


def test_status_context_binding_changes_with_deployment_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        orchestrator.GenesisChecks,
        "capture",
        lambda _self, _arguments, _reason, **_kwargs: "a" * 40,
    )
    baseline = _config(tmp_path)
    bindings = {
        orchestrator.GenesisOrchestrator(candidate).target_binding
        for candidate in (
            baseline,
            replace(baseline, region="eastus", work_dir=tmp_path / "eastus"),
            replace(baseline, environment="staging", work_dir=tmp_path / "staging"),
            replace(baseline, repository="example/other", work_dir=tmp_path / "repository"),
        )
    }

    assert len(bindings) == 4


def _complete_provider_stage(instance: orchestrator.GenesisOrchestrator) -> bool:
    instance.store.update(stage="providers", state="running", completed=True)
    return True


def test_orchestrator_rejects_a_symlinked_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    target = tmp_path / "outside-lock"
    target.write_text("", encoding="ascii")
    target.chmod(0o600)
    (instance.work_dir / "orchestration.lock").symlink_to(target)

    with pytest.raises(orchestrator.OrchestrationError, match="unsafe_orchestration_lock"):
        orchestrator.GenesisOrchestrator._acquire_lock(instance)


def test_expired_total_deadline_blocks_the_next_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    instance.store.deadline_at = "2000-01-01T00:00:00Z"
    invoked: list[str] = []

    with pytest.raises(orchestrator.OrchestrationError, match="orchestration_deadline_exceeded"):
        instance._stage("toolchain", lambda: invoked.append("operation"))

    assert invoked == []


def test_target_and_source_verification_reads_run_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    monkeypatch.setattr(instance, "_verify_target", lambda: barrier.wait(timeout=1))
    monkeypatch.setattr(instance, "_verify_source", lambda: barrier.wait(timeout=1))

    instance._verify_target_and_source()

    assert {"target", "source"} <= instance.store.completed
    assert instance.store.payload["current_stage"] == "source"


def test_orchestrator_preserves_provider_mutation_evidence_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)

    def fail_reconciliation(**_kwargs: Any) -> None:
        raise ProviderReconcileError("failed", mutation_performed=True)

    monkeypatch.setattr(orchestrator, "reconcile_resource_providers", fail_reconciliation)

    with pytest.raises(orchestrator.OrchestrationError, match="resource_provider"):
        instance._reconcile_providers()

    assert instance.store.mutation_performed is True


def _complete_policy_stage(instance: orchestrator.GenesisOrchestrator, route: str) -> str:
    instance.store.route = route
    instance.store.policy_report = {
        "schema_version": "fdai.azure-policy-route.v1",
        "state": "ready",
        "route": route,
        "cleanup_complete": True,
    }
    instance.store.update(stage="policy", state="running", completed=True)
    return route


def test_retry_reuses_verified_policy_evidence_without_another_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _new_orchestrator(tmp_path, monkeypatch)
    _complete_policy_stage(first, "private-runner")
    first.store.update(stage="foundation-plan", state="waiting")
    retry = _new_orchestrator(tmp_path, monkeypatch)
    monkeypatch.setattr(
        retry.checks,
        "run_required",
        lambda *_args, **_kwargs: pytest.fail("completed policy evidence was re-probed"),
    )

    route = retry._probe_policy_route()

    assert route == "private-runner"
    assert retry.store.attempt == 2


def test_private_policy_route_never_invokes_the_public_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    public_calls: list[str] = []
    monkeypatch.setattr(
        instance, "_reconcile_providers", lambda: _complete_provider_stage(instance)
    )
    monkeypatch.setattr(
        instance,
        "_probe_policy_route",
        lambda: _complete_policy_stage(instance, "private-runner"),
    )
    monkeypatch.setattr(instance, "_run_public_preview", lambda: public_calls.append("public"))

    result = instance.run()

    assert result == 2
    assert public_calls == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "waiting"
    assert payload["route"] == "private-runner"
    assert payload["progress_percent"] == 40
    assert payload["reason_code"] == "private_foundation_external_artifacts_required"
    assert payload["next_action"] == (
        "provide_signed_offline_kit_exact_runner_image_and_foundation_profile_then_generate_exact_plan"
    )
    foundation = payload["foundation_report"]["prerequisites"]
    assert foundation["required_count"] == 5
    assert foundation["supplied_count"] == 0
    assert foundation["apply_authorized"] is False


def test_private_route_generates_a_plan_but_still_waits_for_current_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _foundation_inputs(tmp_path)
    instance = _new_orchestrator(
        tmp_path,
        monkeypatch,
        config=replace(_config(tmp_path), foundation_inputs=inputs),
    )
    monkeypatch.setattr(
        instance, "_reconcile_providers", lambda: _complete_provider_stage(instance)
    )
    monkeypatch.setattr(
        instance,
        "_probe_policy_route",
        lambda: _complete_policy_stage(instance, "private-runner"),
    )
    plan_report = {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": "c" * 64,
        "plan_digest": "d" * 64,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    calls: list[dict[str, object]] = []

    def prepare(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return plan_report

    monkeypatch.setattr(private_execution, "prepare_foundation_plan", prepare)

    result = instance.run()

    assert result == 2
    assert len(calls) == 1
    assert calls[0]["inputs"] == inputs
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_code"] == "foundation_exact_plan_approval_required"
    assert payload["foundation_report"]["foundation_plan"] == plan_report
    assert payload["foundation_report"]["current_checkpoint"] == "foundation-plan"
    assert payload["subscription_ready"] is False


def test_foundation_cli_inputs_are_all_or_none_and_absolute(tmp_path: Path) -> None:
    partial = orchestrator._parser().parse_args(["--foundation-offline-kit", str(tmp_path / "kit")])
    with pytest.raises(orchestrator.OrchestrationError, match="foundation_input_set_incomplete"):
        orchestrator._foundation_inputs(partial)

    relative = orchestrator._parser().parse_args(
        [
            "--foundation-offline-kit",
            "kit",
            "--foundation-release-root",
            "release.pem",
            "--foundation-bundle-public-key",
            "bundle.pem",
            "--foundation-profile",
            "profile.json",
            "--foundation-variables-file",
            "variables.json",
        ]
    )
    complete = orchestrator._foundation_inputs(relative)
    assert complete is not None
    with pytest.raises(FoundationPlanError, match="absolute"):
        replace(_config(tmp_path), foundation_inputs=complete).validate()


def test_public_policy_route_stops_at_the_exact_plan_approval_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        instance, "_reconcile_providers", lambda: _complete_provider_stage(instance)
    )
    monkeypatch.setattr(
        instance,
        "_probe_policy_route",
        lambda: _complete_policy_stage(instance, "public-dev"),
    )
    monkeypatch.setattr(instance, "_run_public_preview", lambda: calls.append("preview"))

    result = instance.run()

    assert result == 2
    assert calls == ["preview"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "waiting"
    assert payload["progress_percent"] == 80
    assert payload["skipped_stages"] == list(PRIVATE_FOUNDATION_STAGES)
    assert payload["stages_skipped"] == len(PRIVATE_FOUNDATION_STAGES)
    assert payload["reason_code"] == "public_exact_plan_approval_required"
    assert payload["subscription_ready"] is False


def test_public_preview_is_noninteractive_and_never_sets_apply_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)
    calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def run_required(
        arguments: tuple[str, ...],
        _reason: str,
        *,
        timeout: int,
        env: dict[str, str] | None = None,
        capture: bool = False,
    ) -> None:
        del timeout, capture
        calls.append((arguments, env))

    monkeypatch.setattr(instance.checks, "run_required", run_required)

    instance._run_public_preview()

    assert len(calls) == 2
    preview_arguments, preview_environment = calls[1]
    assert preview_arguments[-1].endswith("/scripts/deployment/azure/azd-up.sh")
    assert preview_environment is not None
    assert preview_environment["FDAI_AZD_CONFIRM"] == "0"
    assert preview_environment["FDAI_AZURE_REGION"] == "koreacentral"


def test_policy_route_is_rejected_without_verified_probe_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _new_orchestrator(tmp_path, monkeypatch)

    def write_incomplete_report(
        arguments: tuple[str, ...],
        _reason: str,
        *,
        timeout: int,
        env: dict[str, str] | None = None,
        capture: bool = False,
    ) -> None:
        del timeout, env
        assert capture is True
        output = Path(arguments[arguments.index("--output-file") + 1])
        output.write_text(
            json.dumps(
                {
                    "schema_version": "fdai.azure-policy-route.v1",
                    "state": "ready",
                    "route": "public-dev",
                    "cleanup_complete": False,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(instance.checks, "run_required", write_incomplete_report)

    with pytest.raises(orchestrator.OrchestrationError, match="policy_probe_incomplete"):
        instance._probe_policy_route()

    assert instance.store.mutation_performed is True


def _write_fake_az(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZ_CALLS"
case "$1 $2" in
  "account show")
    if [[ "$*" == *"--query tenantId"* ]]; then
      printf '%s\n' "$AZURE_TENANT_ID"
    else
      printf '%s\n%s\n' "$AZURE_SUBSCRIPTION_ID" "$AZURE_TENANT_ID"
    fi
    ;;
  "account set") ;;
  "group exists")
    [[ -f "$FAKE_GROUP_STATE" ]] && echo true || echo false
    ;;
    "group show") echo "${FAKE_GROUP_OWNED:-true}" ;;
    "group create")
        touch "$FAKE_GROUP_STATE"
        [[ "${FAKE_GROUP_CREATE_MODE:-success}" != "timeout_after_create" ]] || exit 124
        ;;
    "group delete")
        rm -f "$FAKE_GROUP_STATE"
        if [[ -n "${FAKE_KV_STATE:-}" && -f "$FAKE_KV_STATE" ]]; then
            rm -f "$FAKE_KV_STATE"
            touch "$FAKE_KV_DELETED_STATE"
        fi
        ;;
    "resource list")
        if [[ -f "$FAKE_KV_STATE" ]]; then
            printf '1\t1\n'
        else
            printf '0\t0\n'
        fi
        ;;
    "keyvault create")
        touch "$FAKE_KV_STATE"
            if [[ -n "${FAKE_KV_CREATE_STARTED:-}" ]]; then
                touch "$FAKE_KV_CREATE_STARTED"
                for _ in {1..100}; do
                    [[ -f "$FAKE_STORAGE_CREATE_STARTED" ]] && break
                    sleep 0.01
                done
                [[ -f "$FAKE_STORAGE_CREATE_STARTED" ]] || exit 42
            fi
        [[ "${FAKE_KV_CREATE_MODE:-success}" != "timeout_after_create" ]] || exit 124
        ;;
  "keyvault show") echo "${FAKE_KV_ACCESS:-Enabled}" ;;
    "keyvault list-deleted")
        if [[ -f "$FAKE_KV_DELETED_STATE" ]]; then
            deleted_run_id="${FAKE_KV_DELETED_RUN_ID:-abcdef123456}"
            printf '1\n'
            [[ "$deleted_run_id" == "abcdef123456" ]] && printf '1\n' || printf '0\n'
        else
            printf '0\n0\n'
        fi
        ;;
    "keyvault purge")
        [[ "${FAKE_KV_PURGE_MODE:-success}" == "success" ]] || exit 5
        rm -f "$FAKE_KV_DELETED_STATE"
        ;;
  "storage account")
        if [[ "$3" == "create" && -n "${FAKE_STORAGE_CREATE_STARTED:-}" ]]; then
            touch "$FAKE_STORAGE_CREATE_STARTED"
            for _ in {1..100}; do
                [[ -f "$FAKE_KV_CREATE_STARTED" ]] && break
                sleep 0.01
            done
            [[ -f "$FAKE_KV_CREATE_STARTED" ]] || exit 43
        elif [[ "$3" == "show" ]]; then
      printf '%s\n%s\n' "${FAKE_STORAGE_ACCESS:-Enabled}" "${FAKE_SHARED_KEY:-True}"
    fi
    ;;
  *) exit 9 ;;
esac
""",
        encoding="ascii",
    )
    path.chmod(0o755)


@dataclass(frozen=True, slots=True)
class PolicyProbeExecution:
    result: subprocess.CompletedProcess[str]
    output: Path
    group_state: Path
    deleted_key_vault_state: Path
    invocations: str


def _run_policy_probe(
    tmp_path: Path,
    *,
    group_exists: bool = False,
    deleted_key_vault_exists: bool = False,
    environment: dict[str, str] | None = None,
) -> PolicyProbeExecution:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_az(fake_bin / "az")
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    output = output_dir / "route.json"
    calls = tmp_path / "calls"
    group_state = tmp_path / "group"
    key_vault_state = tmp_path / "key-vault"
    deleted_key_vault_state = tmp_path / "deleted-key-vault"
    if group_exists:
        group_state.touch()
    if deleted_key_vault_exists:
        deleted_key_vault_state.touch()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "AZURE_SUBSCRIPTION_ID": _SUBSCRIPTION,
        "AZURE_TENANT_ID": _TENANT,
        "FDAI_POLICY_PROBE_APPROVED": "1",
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_GROUP_STATE": str(group_state),
        "FAKE_KV_STATE": str(key_vault_state),
        "FAKE_KV_DELETED_STATE": str(deleted_key_vault_state),
        **(environment or {}),
    }
    result = subprocess.run(  # noqa: S603 - controlled repository script
        [
            str(_ROOT / "infra/bootstrap/preflight-policy-check.sh"),
            "--run-id",
            "abcdef123456",
            "--output-file",
            str(output),
        ],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return PolicyProbeExecution(
        result=result,
        output=output,
        group_state=group_state,
        deleted_key_vault_state=deleted_key_vault_state,
        invocations=calls.read_text(encoding="ascii"),
    )


@pytest.mark.parametrize(
    ("key_vault_access", "expected_route"),
    (("Enabled", "public-dev"), ("Disabled", "private-runner")),
)
def test_policy_probe_routes_from_effective_posture_and_verifies_cleanup(
    tmp_path: Path,
    key_vault_access: str,
    expected_route: str,
) -> None:
    execution = _run_policy_probe(
        tmp_path,
        environment={"FAKE_KV_ACCESS": key_vault_access},
    )

    assert execution.result.returncode == 0, execution.result.stderr
    payload: dict[str, Any] = json.loads(execution.output.read_text(encoding="utf-8"))
    assert payload["route"] == expected_route
    assert payload["cleanup_complete"] is True
    assert payload["subscription_ready"] is False
    assert not execution.group_state.exists()
    assert not execution.deleted_key_vault_state.exists()
    assert execution.invocations.index("account show") < execution.invocations.index("group create")
    assert "group delete" in execution.invocations
    assert execution.invocations.index("group delete") < execution.invocations.index(
        "keyvault purge"
    )


def test_policy_probe_creates_independent_resources_concurrently(tmp_path: Path) -> None:
    execution = _run_policy_probe(
        tmp_path,
        environment={
            "FAKE_KV_CREATE_STARTED": str(tmp_path / "kv-started"),
            "FAKE_STORAGE_CREATE_STARTED": str(tmp_path / "storage-started"),
        },
    )

    assert execution.result.returncode == 0, execution.result.stderr
    payload = json.loads(execution.output.read_text(encoding="utf-8"))
    assert payload["key_vault_probe_created"] is True
    assert payload["storage_probe_created"] is True


def test_policy_probe_cleans_up_after_ambiguous_group_create_timeout(tmp_path: Path) -> None:
    execution = _run_policy_probe(
        tmp_path,
        environment={"FAKE_GROUP_CREATE_MODE": "timeout_after_create"},
    )

    assert execution.result.returncode == 4
    assert not execution.group_state.exists()
    assert "group delete" in execution.invocations


def test_policy_probe_cleans_up_after_ambiguous_key_vault_create_timeout(
    tmp_path: Path,
) -> None:
    execution = _run_policy_probe(
        tmp_path,
        environment={"FAKE_KV_CREATE_MODE": "timeout_after_create"},
    )

    assert execution.result.returncode == 4
    payload: dict[str, Any] = json.loads(execution.output.read_text(encoding="utf-8"))
    assert payload["state"] == "incomplete"
    assert payload["cleanup_complete"] is True
    assert "key_vault_probe_create_failed" in payload["reason_codes"]
    assert not execution.group_state.exists()
    assert not execution.deleted_key_vault_state.exists()
    assert "keyvault purge" in execution.invocations


def test_policy_probe_refuses_complete_cleanup_when_key_vault_purge_fails(
    tmp_path: Path,
) -> None:
    execution = _run_policy_probe(
        tmp_path,
        environment={"FAKE_KV_PURGE_MODE": "fail"},
    )

    assert execution.result.returncode == 4
    payload: dict[str, Any] = json.loads(execution.output.read_text(encoding="utf-8"))
    assert payload["state"] == "incomplete"
    assert payload["route"] == "incomplete"
    assert payload["cleanup_complete"] is False
    assert "policy_probe_cleanup_failed" in payload["reason_codes"]
    assert execution.deleted_key_vault_state.exists()


def test_policy_probe_retry_purges_exact_deleted_key_vault_before_recreating(
    tmp_path: Path,
) -> None:
    execution = _run_policy_probe(
        tmp_path,
        deleted_key_vault_exists=True,
    )

    assert execution.result.returncode == 0, execution.result.stderr
    assert execution.invocations.index("keyvault purge") < execution.invocations.index(
        "group create"
    )
    assert execution.invocations.count("keyvault purge") == 2
    assert not execution.deleted_key_vault_state.exists()


def test_policy_probe_never_purges_deleted_key_vault_without_exact_ownership(
    tmp_path: Path,
) -> None:
    execution = _run_policy_probe(
        tmp_path,
        deleted_key_vault_exists=True,
        environment={"FAKE_KV_DELETED_RUN_ID": "999999999999"},
    )

    assert execution.result.returncode == 4
    assert "held by an unrelated deleted resource" in execution.result.stderr
    assert "keyvault purge" not in execution.invocations
    assert "group create" not in execution.invocations
    assert execution.deleted_key_vault_state.exists()


def test_policy_probe_never_deletes_a_group_without_exact_ownership(tmp_path: Path) -> None:
    execution = _run_policy_probe(
        tmp_path,
        group_exists=True,
        environment={"FAKE_GROUP_OWNED": "false"},
    )

    assert execution.result.returncode == 4
    assert execution.group_state.exists()
    assert "group delete" not in execution.invocations


def test_policy_probe_retry_cleans_its_exact_owned_group_before_recreating(
    tmp_path: Path,
) -> None:
    execution = _run_policy_probe(tmp_path, group_exists=True)

    assert execution.result.returncode == 0, execution.result.stderr
    assert execution.invocations.index("group delete") < execution.invocations.index("group create")
    assert not execution.group_state.exists()
