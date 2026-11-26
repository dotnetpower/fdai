from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "verify_model_deployments.py"
)


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_model_deployments", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _resolved() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "capabilities": [
            {
                "name": "t2.reasoner.primary",
                "status": "resolved",
                "family": "gpt-5.4-mini",
                "version": "2026-03-17",
                "sku": "GlobalProvisionedManaged",
                "capacity_unit": "ptu",
                "capacity_tpm": 0,
                "capacity_value": 15,
            },
            {"name": "t2.reasoner.secondary", "status": "hil-only"},
        ],
    }


def _provider(*, capacity: int = 15) -> dict[str, object]:
    return {
        "value": [
            {
                "name": "t2.reasoner.primary",
                "properties": {
                    "model": {"name": "gpt-5.4-mini", "version": "2026-03-17"},
                    "provisioningState": "Succeeded",
                },
                "sku": {"name": "GlobalProvisionedManaged", "capacity": capacity},
            },
            {
                "name": "unrelated-deployment",
                "properties": {
                    "model": {"name": "gpt-4o", "version": "2024-11-20"},
                    "provisioningState": "Succeeded",
                },
                "sku": {"name": "GlobalStandard", "capacity": 1},
            },
        ]
    }


def _write(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_verifies_exact_provider_binding_without_resource_identity(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    resolved = _write(tmp_path, "resolved.json", _resolved())
    provider = _write(tmp_path, "provider.json", _provider())
    output = tmp_path / "receipt.json"

    receipt = module.verify_model_deployments(resolved, provider, output)

    assert receipt["schema_version"] == "fdai.model-deployment-readback.v1"
    assert receipt["verified_deployments"] == [
        {
            "capability": "t2.reasoner.primary",
            "family": "gpt-5.4-mini",
            "version": "2026-03-17",
            "sku": "GlobalProvisionedManaged",
            "capacity": 15,
            "provisioning_state": "Succeeded",
        }
    ]
    serialized = output.read_text(encoding="utf-8")
    assert "subscriptions" not in serialized
    assert "resourceGroups" not in serialized
    assert "openai.azure.com" not in serialized


def test_rejects_provider_capacity_mismatch(module: ModuleType, tmp_path: Path) -> None:
    resolved = _write(tmp_path, "resolved.json", _resolved())
    provider = _write(tmp_path, "provider.json", _provider(capacity=10))

    with pytest.raises(module.ModelDeploymentVerificationError, match="does not match"):
        module.verify_model_deployments(resolved, provider, tmp_path / "receipt.json")


def test_rejects_duplicate_resolved_capability(module: ModuleType, tmp_path: Path) -> None:
    resolved_payload = _resolved()
    capabilities = resolved_payload["capabilities"]
    assert isinstance(capabilities, list)
    capabilities.insert(1, dict(capabilities[0]))
    resolved = _write(tmp_path, "resolved.json", resolved_payload)
    provider = _write(tmp_path, "provider.json", _provider())

    with pytest.raises(module.ModelDeploymentVerificationError, match="duplicated"):
        module.verify_model_deployments(resolved, provider, tmp_path / "receipt.json")


def test_selected_capabilities_ignore_unrelated_deployment_drift(
    module: ModuleType, tmp_path: Path
) -> None:
    resolved_payload = _resolved()
    capabilities = resolved_payload["capabilities"]
    assert isinstance(capabilities, list)
    capabilities.insert(
        0,
        {
            "name": "t1.embedding",
            "status": "resolved",
            "family": "text-embedding-3-large",
            "version": "1",
            "sku": "Standard",
            "capacity_tpm": 200_000,
        },
    )
    resolved = _write(tmp_path, "resolved.json", resolved_payload)
    provider = _write(tmp_path, "provider.json", _provider())

    receipt = module.verify_model_deployments(
        resolved,
        provider,
        tmp_path / "receipt.json",
        capability_names=frozenset({"t2.reasoner.primary"}),
    )

    assert [item["capability"] for item in receipt["verified_deployments"]] == [
        "t2.reasoner.primary"
    ]
