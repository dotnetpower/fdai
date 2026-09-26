"""Production startup binds shadow comparisons to its existing state store."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fdai.composition import Container
from fdai.runtime import bootstrap
from fdai.shared.providers.testing.state_store import InMemoryStateStore


@pytest.mark.parametrize("drain_fails", [False, True])
async def test_consumer_bootstrap_binds_and_drains_context_shadow(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    drain_fails: bool,
) -> None:
    store = InMemoryStateStore()
    observed: list[str] = []

    class _Resources:
        health_server: Any = None
        http_client: Any = None
        state_store: Any = None
        development_diagnostics: Any = None

        async def close(self) -> None:
            observed.append("close")

    async def _open_health_port() -> object:
        return object()

    async def _load_values(**_: object) -> dict[str, object]:
        return {}

    async def _build_core_runtime(**kwargs: object) -> None:
        bound = kwargs["container"]
        assert isinstance(bound, Container)
        assert kwargs["state_store"] is store
        runner = bound.context_selection_shadow_runner
        assert runner is not None
        assert bound.context_selection_policy_authority is runner._authority
        observed.append("bound")

        async def _drain() -> None:
            observed.append("drain")
            if drain_fails:
                raise RuntimeError("drain failed")

        monkeypatch.setattr(runner, "drain", _drain)
        raise RuntimeError("stop after production composition")

    plan = SimpleNamespace(
        start_consumer=True,
        identity_requests=SimpleNamespace(
            case_history=False, configuration_drift=False, telemetry=False
        ),
        requires_initial_identity=False,
        consumer_requires_workload_identity=False,
    )
    monkeypatch.setattr(bootstrap, "default_container_from_env", lambda: container)
    monkeypatch.setattr(bootstrap, "build_bootstrap_plan", lambda **_: plan)
    monkeypatch.setattr(bootstrap, "build_development_diagnostics", lambda *_, **__: None)
    monkeypatch.setattr(bootstrap, "open_health_port", _open_health_port)
    monkeypatch.setattr(bootstrap, "RuntimeResources", _Resources)
    monkeypatch.setattr(bootstrap, "_build_audit_store", lambda: store)
    monkeypatch.setattr(bootstrap, "_load_runtime_values", _load_values)
    monkeypatch.setattr(bootstrap, "_attach_runtime_knowledge_source", lambda bound: bound)
    monkeypatch.setattr(bootstrap, "build_runtime_license_authority", lambda **_: object())
    monkeypatch.setattr(bootstrap, "build_core_runtime", _build_core_runtime)

    with pytest.raises(
        RuntimeError,
        match="drain failed" if drain_fails else "stop after production composition",
    ):
        await bootstrap._run()

    assert observed == ["bound", "drain", "close"]
