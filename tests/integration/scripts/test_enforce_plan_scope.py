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


def test_rca_reader_identity_scope_accepts_only_identity_and_role() -> None:
    identity = "module.rca_reader_identity.azurerm_user_assigned_identity.primary"
    role = "azurerm_role_assignment.rca_monitoring_reader"

    assert enforce(_plan(identity, role), mode="rca-reader-identity") == frozenset({identity, role})
    assert enforce({"resource_changes": []}, mode="rca-reader-identity") == frozenset()
    with pytest.raises(ValueError, match="outside its bounded scope"):
        enforce(
            _plan(identity, role, "module.compute.container_app"),
            mode="rca-reader-identity",
        )


def test_operational_history_scope_accepts_only_storage_endpoint_and_job() -> None:
    storage = "module.operational_history_storage[0].azurerm_storage_account.case_history"
    endpoint = "azurerm_private_endpoint.operational_history_blob[0]"
    job = "module.compute.azurerm_container_app_job.operational_history_lifecycle[0]"

    assert enforce(
        _plan(storage, endpoint, job),
        mode="operational-history",
    ) == frozenset({storage, endpoint, job})
    with pytest.raises(ValueError, match="outside its bounded scope"):
        enforce(
            _plan(storage, "module.compute.azurerm_container_app.core"),
            mode="operational-history",
        )


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
    account = "module.llm_azure_openai[0].azurerm_cognitive_account.primary"
    judge = 'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.judge"]'
    primary = (
        'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t2.reasoner.primary"]'
    )

    plan = _plan(judge, primary)
    plan["resource_changes"].append({"address": account, "change": {"actions": ["update"]}})
    assert enforce(plan, mode="core-model-quorum") == frozenset({account, judge, primary})
    assert enforce({"resource_changes": []}, mode="core-model-quorum") == frozenset()
    with pytest.raises(ValueError, match="exactly the required resources"):
        enforce(_plan(judge), mode="core-model-quorum")
    with pytest.raises(ValueError, match="exactly the required resources"):
        enforce(_plan(account, judge, primary, "module.console[0].site"), mode="core-model-quorum")

    destructive_account = _plan(judge, primary)
    destructive_account["resource_changes"].append(
        {"address": account, "change": {"actions": ["delete", "create"]}}
    )
    with pytest.raises(ValueError, match="in-place update"):
        enforce(destructive_account, mode="core-model-quorum")

    updating_deployment = _plan(judge, primary)
    updating_deployment["resource_changes"][0]["change"]["actions"] = ["update"]
    updating_deployment["resource_changes"].append(
        {"address": account, "change": {"actions": ["update"]}}
    )
    with pytest.raises(ValueError, match="create-only"):
        enforce(updating_deployment, mode="core-model-quorum")


def test_core_model_quorum_accepts_only_exact_primary_replacement() -> None:
    primary = (
        'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t2.reasoner.primary"]'
    )
    plan = {
        "resource_changes": [
            {
                "address": primary,
                "change": {
                    "actions": ["delete", "create"],
                    "before": {
                        "model": [{"name": "gpt-4o", "version": "2024-11-20"}],
                        "sku": [{"name": "GlobalStandard", "capacity": 1}],
                    },
                    "after": {
                        "model": [{"name": "gpt-5.4", "version": "2026-03-05"}],
                        "sku": [{"name": "GlobalStandard", "capacity": 100}],
                    },
                },
            }
        ]
    }
    resolved = {
        "capabilities": [
            {
                "name": "t2.reasoner.primary",
                "family": "gpt-5.4",
                "version": "2026-03-05",
                "sku": "GlobalStandard",
                "capacity_tpm": 100_000,
            }
        ]
    }

    assert enforce(plan, mode="core-model-quorum", resolved_models=resolved) == frozenset({primary})
    plan["resource_changes"][0]["change"]["before"]["model"][0]["name"] = "gpt-4.1"
    with pytest.raises(ValueError, match="does not match the profile"):
        enforce(plan, mode="core-model-quorum", resolved_models=resolved)


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
