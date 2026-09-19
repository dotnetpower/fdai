from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/deployment/service/manual_operator_platform.py"
)
_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("manual_operator_platform", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_platform_root_owns_exact_existing_state_addresses(platform: ModuleType) -> None:
    assert platform._ADDRESSES == {
        "random_id.cost_pseudonym_key[0]",
        "azurerm_key_vault_secret.cost_pseudonym_key[0]",
        "azurerm_role_assignment.operator_cost_pseudonym_secret_reader[0]",
    }
    terraform = (_ROOT / "infra/operator-platform-prerequisite/main.tf").read_text(encoding="utf-8")
    assert 'resource "random_id" "cost_pseudonym_key"' in terraform
    assert 'resource "azurerm_key_vault_secret" "cost_pseudonym_key"' in terraform
    assert 'resource "azurerm_role_assignment" "operator_cost_pseudonym_secret_reader"' in terraform
    assert terraform.count("count") == 3
    assert "fdai-cost-pseudonym-key" in terraform
    assert "/subscriptions/" not in terraform


def test_platform_plan_accepts_only_exact_create_set(platform: ModuleType) -> None:
    plan = {
        "resource_changes": [
            {"address": address, "change": {"actions": ["create"]}}
            for address in sorted(platform._ADDRESSES)
        ],
        "output_changes": {"cost_pseudonym_key_secret_id": {"actions": ["update"]}},
    }

    platform._validate_plan(plan)


def test_platform_plan_rejects_unrelated_or_incomplete_changes(platform: ModuleType) -> None:
    plan = {
        "resource_changes": [
            {"address": address, "change": {"actions": ["create"]}}
            for address in sorted(platform._ADDRESSES)[:-1]
        ],
        "output_changes": {"cost_pseudonym_key_secret_id": {"actions": ["update"]}},
    }
    plan["resource_changes"].append(
        {"address": "azurerm_resource_group.unrelated", "change": {"actions": ["update"]}}
    )

    with pytest.raises(
        platform.common.ManualOperatorUpdateError,
        match="exceeds the prerequisite boundary",
    ):
        platform._validate_plan(plan)


def test_platform_plan_rejects_drift(platform: ModuleType) -> None:
    plan = {
        "resource_changes": [
            {"address": address, "change": {"actions": ["create"]}}
            for address in sorted(platform._ADDRESSES)
        ],
        "resource_drift": [{"address": "existing"}],
        "output_changes": {"cost_pseudonym_key_secret_id": {"actions": ["update"]}},
    }

    with pytest.raises(
        platform.common.ManualOperatorUpdateError,
        match="unresolved drift",
    ):
        platform._validate_plan(plan)


def test_platform_receipt_rejects_changed_readback(tmp_path: Path, platform: ModuleType) -> None:
    review = {"review_digest": "a" * 64}
    receipt: dict[str, object] = {
        "schema_version": "fdai.manual-operator-platform-receipt.v1",
        "review_digest": review["review_digest"],
        "secret_readback_verified": True,
        "role_readback_verified": True,
    }
    receipt["receipt_digest"] = platform.common._canonical_digest(receipt)
    receipt["role_readback_verified"] = False
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        platform.common.ManualOperatorUpdateError,
        match="platform receipt is invalid",
    ):
        platform._receipt(path, review)
