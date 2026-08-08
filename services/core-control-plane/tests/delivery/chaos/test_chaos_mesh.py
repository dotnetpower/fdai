"""Unit tests for the Chaos Mesh CRD injector + probe.

``kubectl`` is fully mocked, so these never touch a real cluster - they lock
the command shape (apply/delete) and the ``AllInjected`` parse logic.
"""

from __future__ import annotations

import json

import fdai.delivery.chaos.chaos_mesh as cm
import pytest

_CRD = "apiVersion: chaos-mesh.org/v1alpha1\nkind: StressChaos\nmetadata:\n  name: demo\n"


def _fake_kubectl(script):  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []

    async def runner(args, *, context, kubectl="kubectl", stdin=None, timeout=60.0):  # type: ignore[no-untyped-def]
        calls.append({"args": list(args), "context": context, "stdin": stdin})
        return script(list(args))

    return runner, calls


def test_injector_exposes_fault_type() -> None:
    inj = cm.ChaosMeshInjector(
        fault_type="cpu_stress",
        context="ctx",
        kind="stresschaos",
        name="demo",
        namespace="demo",
        crd_yaml=_CRD,
    )
    assert inj.fault_type == "cpu_stress"


async def test_inject_applies_crd_via_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_kubectl(lambda args: (0, "created", ""))
    monkeypatch.setattr(cm, "_kubectl", runner)
    inj = cm.ChaosMeshInjector(
        fault_type="cpu_stress",
        context="ctx",
        kind="stresschaos",
        name="demo",
        namespace="demo",
        crd_yaml=_CRD,
    )
    await inj.inject(target="app=x", params={})
    assert calls[0]["args"] == ["apply", "-f", "-"]
    assert calls[0]["stdin"] == _CRD


async def test_inject_raises_on_apply_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_kubectl(lambda args: (1, "", "bad crd"))
    monkeypatch.setattr(cm, "_kubectl", runner)
    inj = cm.ChaosMeshInjector(
        fault_type="cpu_stress",
        context="ctx",
        kind="stresschaos",
        name="demo",
        namespace="demo",
        crd_yaml=_CRD,
    )
    with pytest.raises(RuntimeError, match="chaos-mesh apply"):
        await inj.inject(target="app=x", params={})


async def test_stop_deletes_crd(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_kubectl(lambda args: (0, "deleted", ""))
    monkeypatch.setattr(cm, "_kubectl", runner)
    inj = cm.ChaosMeshInjector(
        fault_type="cpu_stress",
        context="ctx",
        kind="stresschaos",
        name="demo",
        namespace="demo",
        crd_yaml=_CRD,
    )
    await inj.stop(target="app=x")
    args = calls[0]["args"]
    assert "delete" in args and "stresschaos" in args and "demo" in args
    assert "--ignore-not-found" in args


def _probe() -> cm.ChaosMeshInjectedProbe:
    return cm.ChaosMeshInjectedProbe(
        context="ctx", kind="stresschaos", name="demo", namespace="demo"
    )


async def _observe(monkeypatch, payload):  # type: ignore[no-untyped-def]
    runner, _ = _fake_kubectl(lambda args: (0, json.dumps(payload), ""))
    monkeypatch.setattr(cm, "_kubectl", runner)
    return await _probe().observed(signal="s", targets=["t"])


async def test_probe_true_on_all_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}
    assert await _observe(monkeypatch, payload) is True


async def test_probe_false_when_not_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": {"conditions": [{"type": "AllInjected", "status": "False"}]}}
    assert await _observe(monkeypatch, payload) is False


async def test_probe_fallback_on_desired_phase_run(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": {
            "conditions": [],
            "experiment": {"desiredPhase": "Run", "podRecords": [{"id": "p1"}]},
        }
    }
    assert await _observe(monkeypatch, payload) is True


async def test_probe_false_on_error_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_kubectl(lambda args: (1, "", "not found"))
    monkeypatch.setattr(cm, "_kubectl", runner)
    assert await _probe().observed(signal="s", targets=["t"]) is False


async def test_probe_false_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_kubectl(lambda args: (0, "not-json", ""))
    monkeypatch.setattr(cm, "_kubectl", runner)
    assert await _probe().observed(signal="s", targets=["t"]) is False
