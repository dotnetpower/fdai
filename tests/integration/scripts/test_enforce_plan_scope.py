from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/enforce_plan_scope.py"
_SPEC = importlib.util.spec_from_file_location("enforce_plan_scope", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
enforce = _MODULE.enforce


def _plan(*addresses: str) -> dict[str, object]:
    return {
        "resource_changes": [
            {"address": address, "change": {"actions": ["create"]}} for address in addresses
        ]
    }


def test_design_mock_scope_accepts_only_static_site() -> None:
    address = "module.design_mocks[0].azurerm_static_web_app.design_mocks"

    assert enforce(_plan(address), mode="design-mocks") == frozenset({address})
    with pytest.raises(ValueError, match="bounded scope"):
        enforce(_plan(address, "module.console[0].site"), mode="design-mocks")


def test_monitoring_scope_accepts_only_monitoring_module() -> None:
    address = "module.monitoring[0].azurerm_monitor_metric_alert.primary"

    assert enforce(_plan(address), mode="monitoring") == frozenset({address})
    with pytest.raises(ValueError, match="outside module.monitoring"):
        enforce(_plan("module.compute.container_app"), mode="monitoring")


def test_model_scope_uses_non_hil_sealed_capabilities() -> None:
    allowed = 'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.embedding"]'
    resolved = {
        "capabilities": [
            {"name": "t1.embedding", "status": "ready"},
            {"name": "t2.reasoner", "status": "hil-only"},
        ]
    }

    assert enforce(_plan(allowed), mode="model-binding", resolved_models=resolved) == frozenset(
        {allowed}
    )
    with pytest.raises(ValueError, match="bounded scope"):
        enforce(
            _plan(
                'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t2.reasoner"]'
            ),
            mode="model-binding",
            resolved_models=resolved,
        )


def test_model_scope_requires_a_change() -> None:
    with pytest.raises(ValueError, match="contains no deployment change"):
        enforce(
            {"resource_changes": []},
            mode="model-binding",
            resolved_models={"capabilities": []},
        )


def test_core_model_quorum_requires_exact_required_pair() -> None:
    judge = 'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.judge"]'
    primary = (
        'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t2.reasoner.primary"]'
    )

    assert enforce(_plan(judge, primary), mode="core-model-quorum") == frozenset({judge, primary})
    with pytest.raises(ValueError, match="exactly the required deployments"):
        enforce(_plan(judge), mode="core-model-quorum")
    with pytest.raises(ValueError, match="exactly the required deployments"):
        enforce(_plan(judge, primary, "module.console[0].site"), mode="core-model-quorum")


def test_read_and_noop_actions_are_ignored() -> None:
    plan = {
        "resource_changes": [
            {"address": "data.current", "change": {"actions": ["read"]}},
            {"address": "module.unchanged", "change": {"actions": ["no-op"]}},
        ]
    }

    assert enforce(plan, mode="design-mocks") == frozenset()


def test_main_renders_plan_from_its_terraform_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = tmp_path / "dev.plan"
    plan_path.touch()
    address = "module.design_mocks[0].azurerm_static_web_app.design_mocks"
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        observed.update(argv=argv, kwargs=kwargs)
        return SimpleNamespace(stdout=json.dumps(_plan(address)))

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["enforce_plan_scope.py", "--plan", str(plan_path), "--mode", "design-mocks"],
    )

    assert _MODULE.main() == 0
    assert observed["argv"] == ["terraform", "show", "-json", "dev.plan"]
    assert observed["kwargs"]["cwd"] == tmp_path
