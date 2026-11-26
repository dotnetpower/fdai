from __future__ import annotations

import json

from fdai.delivery.chaos import litmus


async def test_inject_applies_engine_and_stop_is_idempotent(monkeypatch) -> None:
    calls: list[list[str]] = []

    async def fake_kubectl(args, **kwargs):
        calls.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(litmus, "_kubectl", fake_kubectl)
    injector = litmus.LitmusChaosInjector(
        fault_type="stop",
        context="ctx",
        engine_name="engine",
        namespace="litmus",
        engine_yaml="kind: ChaosEngine\n",
    )

    await injector.inject(target="demo", params={})
    await injector.stop(target="demo")

    assert injector.fault_type == "stop"
    assert calls[0] == ["apply", "-f", "-"]
    assert calls[1][:3] == ["patch", "chaosengine", "engine"]
    assert calls[2][:3] == ["delete", "chaosengine", "engine"]


async def test_probe_accepts_injected_target(monkeypatch) -> None:
    async def fake_kubectl(args, **kwargs):
        body = {"status": {"history": {"targets": [{"chaosStatus": "injected"}]}}}
        return 0, json.dumps(body), ""

    monkeypatch.setattr(litmus, "_kubectl", fake_kubectl)
    probe = litmus.LitmusChaosResultProbe(
        context="ctx",
        engine_name="engine",
        experiment_name="pod-delete",
        namespace="litmus",
    )

    assert await probe.observed(signal="pod_restart", targets=["demo"]) is True


async def test_probe_fails_closed_on_bad_result(monkeypatch) -> None:
    async def fake_kubectl(args, **kwargs):
        return 0, "not-json", ""

    monkeypatch.setattr(litmus, "_kubectl", fake_kubectl)
    probe = litmus.LitmusChaosResultProbe(
        context="ctx",
        engine_name="engine",
        experiment_name="pod-delete",
        namespace="litmus",
    )

    assert await probe.observed(signal="pod_restart", targets=["demo"]) is False
