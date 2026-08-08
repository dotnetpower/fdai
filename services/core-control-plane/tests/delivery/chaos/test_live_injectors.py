"""Unit tests for the live (enforce) chaos injectors + probes.

Subprocess is fully mocked (``_run`` monkeypatched), so these never touch a
real cluster or Azure - they lock the command shape and the parse logic.
"""

from __future__ import annotations

import json

import fdai.delivery.chaos.live_injectors as li
import pytest


def _fake_run(script):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    async def runner(cmd, *, timeout=60.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return script(list(cmd))

    return runner, calls


# --------------------------------------------------------------------------
# fault_type identifiers must match the scenario catalog
# --------------------------------------------------------------------------


def test_fault_types_match_scenarios() -> None:
    assert li.KubectlPodKillInjector(context="c", namespace="n").fault_type == "pod_kill"
    assert (
        li.KubectlBadDeployInjector(
            context="c", namespace="n", deployment="d", container="x", bad_image="i"
        ).fault_type
        == "bad_deploy"
    )
    assert li.AzVmCpuStressInjector(resource_group="rg", vm_name="vm").fault_type == "vm_cpu_stress"


# --------------------------------------------------------------------------
# Pod kill
# --------------------------------------------------------------------------


async def test_pod_kill_deletes_first_matching_pod(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(cmd: list[str]):
        if "get" in cmd and "pods" in cmd:
            return (0, "nginx-demo-abc123", "")
        return (0, "", "")

    runner, calls = _fake_run(script)
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlPodKillInjector(context="ctx", namespace="demo")
    await inj.inject(target="app=nginx-demo", params={"grace_period_seconds": "0"})
    assert any("delete" in c and "nginx-demo-abc123" in c for c in calls)


async def test_pod_kill_raises_when_no_pod(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (0, "", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlPodKillInjector(context="ctx", namespace="demo")
    with pytest.raises(RuntimeError, match="no pod for selector"):
        await inj.inject(target="app=missing", params={})


async def test_pod_kill_stop_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlPodKillInjector(context="ctx", namespace="demo")
    await inj.stop(target="app=nginx-demo")
    assert calls == []  # ReplicaSet self-heals; nothing to undo.


# --------------------------------------------------------------------------
# Pod restart probe
# --------------------------------------------------------------------------


async def _observe(probe, monkeypatch, payload):  # type: ignore[no-untyped-def]
    runner, _ = _fake_run(lambda cmd: (0, json.dumps(payload), ""))
    monkeypatch.setattr(li, "_run", runner)
    return await probe.observed(signal="s", targets=["t"])


async def test_pod_restart_probe_true_on_kill_and_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"items": [{"reason": "Killing"}, {"reason": "SuccessfulCreate"}]}
    probe = li.KubeEventPodRestartProbe(context="c", namespace="n")
    assert await _observe(probe, monkeypatch, payload) is True


async def test_pod_restart_probe_false_without_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"items": [{"reason": "Killing"}]}
    probe = li.KubeEventPodRestartProbe(context="c", namespace="n")
    assert await _observe(probe, monkeypatch, payload) is False


# --------------------------------------------------------------------------
# Bad deploy + rollout stall probe
# --------------------------------------------------------------------------


async def test_bad_deploy_stop_runs_rollout_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlBadDeployInjector(
        context="c", namespace="n", deployment="nginx-demo", container="nginx", bad_image="bad:404"
    )
    await inj.stop(target="deployment:nginx-demo")
    assert any("rollout" in c and "undo" in c for c in calls)


async def test_rollout_stall_probe_true_on_imagepullbackoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "status": {
                    "containerStatuses": [{"state": {"waiting": {"reason": "ImagePullBackOff"}}}]
                }
            }
        ]
    }
    probe = li.KubeRolloutStallProbe(context="c", namespace="n", selector="app=x")
    assert await _observe(probe, monkeypatch, payload) is True


async def test_rollout_stall_probe_false_when_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"items": [{"status": {"containerStatuses": [{"state": {"running": {}}}]}}]}
    probe = li.KubeRolloutStallProbe(context="c", namespace="n", selector="app=x")
    assert await _observe(probe, monkeypatch, payload) is False


# --------------------------------------------------------------------------
# VM CPU stress + Azure Monitor probe
# --------------------------------------------------------------------------


async def test_vm_stress_stop_kills_stress(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "stopped", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.AzVmCpuStressInjector(resource_group="rg", vm_name="vm")
    await inj.stop(target="vm:vm")
    joined = [" ".join(c) for c in calls]
    assert any("pkill -f stress-ng" in j for j in joined)


async def test_azmonitor_probe_true_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _ = _fake_run(lambda cmd: (0, json.dumps([1.2, 83.9, 70.0]), ""))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzureMonitorCpuProbe(vm_resource_id="/vm/id", threshold_pct=50.0)
    assert await probe.observed(signal="host_cpu", targets=["vm"]) is True


async def test_azmonitor_probe_false_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _ = _fake_run(lambda cmd: (0, json.dumps([1.2, 3.4, 5.0]), ""))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzureMonitorCpuProbe(vm_resource_id="/vm/id", threshold_pct=50.0)
    assert await probe.observed(signal="host_cpu", targets=["vm"]) is False


async def test_azmonitor_probe_false_on_error_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (1, "", "boom"))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzureMonitorCpuProbe(vm_resource_id="/vm/id", threshold_pct=50.0)
    assert await probe.observed(signal="host_cpu", targets=["vm"]) is False


# --------------------------------------------------------------------------
# _run drops AZURE_CONFIG_DIR only when asked
# --------------------------------------------------------------------------


async def test_run_drops_azure_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Proc:
        returncode = 0

        async def communicate(self):  # type: ignore[no-untyped-def]
            return (b"ok", b"")

    async def fake_exec(*cmd, stdout=None, stderr=None, env=None):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return _Proc()

    monkeypatch.setenv("AZURE_CONFIG_DIR", "/home/x/.azure-customer")
    monkeypatch.setattr(li.asyncio, "create_subprocess_exec", fake_exec)
    await li._run(["az", "account", "show"], drop_azure_config_dir=True)
    env = captured["env"]
    assert isinstance(env, dict)
    assert "AZURE_CONFIG_DIR" not in env


async def test_run_keeps_env_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Proc:
        returncode = 0

        async def communicate(self):  # type: ignore[no-untyped-def]
            return (b"ok", b"")

    async def fake_exec(*cmd, stdout=None, stderr=None, env=None):  # type: ignore[no-untyped-def]
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr(li.asyncio, "create_subprocess_exec", fake_exec)
    await li._run(["kubectl", "get", "pods"])
    assert captured["env"] is None  # inherit parent env unchanged


# --------------------------------------------------------------------------
# VM memory stress + host-memory probe (S6)
# --------------------------------------------------------------------------


def test_mem_stress_fault_type() -> None:
    inj = li.AzVmMemStressInjector(resource_group="rg", vm_name="vm")
    assert inj.fault_type == "vm_mem_stress"


async def test_mem_stress_inject_uses_setsid_and_param_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "started", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.AzVmMemStressInjector(resource_group="rg", vm_name="vm", vm_bytes="85%")
    await inj.inject(target="vm:vm", params={"vm_bytes": "350M"})
    script = " ".join(calls[0])
    assert "setsid stress-ng --vm 1 --vm-bytes 350M" in script  # param overrides default
    assert "nohup" not in script  # setsid detaches so it survives run-command exit


async def test_mem_stress_stop_kills_stress(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "stopped", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.AzVmMemStressInjector(resource_group="rg", vm_name="vm")
    await inj.stop(target="vm:vm")
    assert any("pkill -f stress-ng" in " ".join(c) for c in calls)


async def test_mem_stress_inject_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (1, "", "boom"))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.AzVmMemStressInjector(resource_group="rg", vm_name="vm")
    with pytest.raises(RuntimeError, match="mem-stress inject failed"):
        await inj.inject(target="vm:vm", params={})


async def test_mem_probe_true_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (0, "Enable succeeded: \n[stdout]\n127\n[stderr]\n", ""))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzVmMemProbe(resource_group="rg", vm_name="vm", min_available_mb=400)
    assert await probe.observed(signal="host_memory", targets=["vm"]) is True


async def test_mem_probe_false_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (0, "Enable succeeded: \n[stdout]\n612\n[stderr]\n", ""))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzVmMemProbe(resource_group="rg", vm_name="vm", min_available_mb=400)
    assert await probe.observed(signal="host_memory", targets=["vm"]) is False


async def test_mem_probe_false_on_error_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(lambda cmd: (1, "", "boom"))
    monkeypatch.setattr(li, "_run", runner)
    probe = li.AzVmMemProbe(resource_group="rg", vm_name="vm", min_available_mb=400)
    assert await probe.observed(signal="host_memory", targets=["vm"]) is False


def test_extract_int_pulls_first_integer() -> None:
    assert li._extract_int("Enable succeeded: \n[stdout]\n127\n[stderr]\n") == 127
    assert li._extract_int("no digits here") is None


# --------------------------------------------------------------------------
# Backend-down injector + backend-health probe (S11)
# --------------------------------------------------------------------------


def test_backend_down_fault_type() -> None:
    inj = li.KubectlBackendDownInjector(
        context="c", namespace="n", deployment="d", restore_replicas=3
    )
    assert inj.fault_type == "pod_kill"


async def test_backend_down_scales_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlBackendDownInjector(
        context="c", namespace="n", deployment="nginx-demo", restore_replicas=3
    )
    await inj.inject(target="deployment:nginx-demo", params={})
    assert any("scale" in c and "--replicas=0" in c for c in calls)


async def test_backend_down_stop_restores_replicas(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run(lambda cmd: (0, "", ""))
    monkeypatch.setattr(li, "_run", runner)
    inj = li.KubectlBackendDownInjector(
        context="c", namespace="n", deployment="nginx-demo", restore_replicas=3
    )
    await inj.stop(target="deployment:nginx-demo")
    assert any("scale" in c and "--replicas=3" in c for c in calls)


async def test_backend_health_probe_true_when_no_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"subsets": []}
    probe = li.KubeBackendHealthProbe(context="c", namespace="n", service="svc")
    assert await _observe(probe, monkeypatch, payload) is True


async def test_backend_health_probe_false_when_endpoints_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]}
    probe = li.KubeBackendHealthProbe(context="c", namespace="n", service="svc")
    assert await _observe(probe, monkeypatch, payload) is False
