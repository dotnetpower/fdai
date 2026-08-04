from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.dynamic_assurance import DynamicAssurancePanel
from fdai.shared.providers.testing import InMemoryStateStore


async def test_dynamic_assurance_projects_models_and_trajectory_status() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "dynamic-effect-model:active:one",
        {
            "model_id": "scalar-active",
            "version": "1.0.0",
            "revision": 2,
            "sample_count": 30,
            "mean_absolute_error": 2.5,
        },
    )
    await store.write_state(
        "dynamic-graph-effect-model:challenger:one",
        {
            "model_id": "graph-challenger",
            "version": "1.1.0",
            "revision": 4,
            "sample_count": 12,
            "mean_absolute_error": 1.25,
        },
    )
    await store.write_state(
        "dynamic-trajectory-episode:open",
        {"status": "open"},
    )
    await store.write_state(
        "dynamic-trajectory-episode:closed",
        {"status": "closed"},
    )

    result = await DynamicAssurancePanel(store).render(params={})

    assert result["source"] == "state-store"
    assert result["authority"] == "read-only-evidence"
    assert result["models"]["scalar_active"] == {
        "count": 1,
        "sample_count": 30,
        "max_mean_absolute_error": 2.5,
        "model_refs": ["scalar-active@1.0.0:r2"],
    }
    assert result["models"]["graph_challenger"]["count"] == 1
    assert result["trajectories"] == {
        "total": 2,
        "open": 1,
        "closed": 1,
        "unknown": 0,
    }
    assert result["truncated"] is False


async def test_dynamic_assurance_returns_honest_empty_state() -> None:
    result = await DynamicAssurancePanel(InMemoryStateStore()).render(params={})

    assert result["models"]["scalar_active"]["count"] == 0
    assert result["trajectories"]["total"] == 0


def test_dynamic_assurance_is_registered_as_get_only_reader_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")
    panel = DynamicAssurancePanel(InMemoryStateStore())
    application = build_app(
        authenticator=build_authenticator(
            verifier=lambda token: {"oid": "reader"},
            resolver=lambda claims: None,
        ),
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(dev_mode=True, extra_panels=(panel,)),
    )
    client = TestClient(application)

    assert client.get("/dynamic-assurance").status_code == 200
    assert client.post("/dynamic-assurance").status_code == 405
