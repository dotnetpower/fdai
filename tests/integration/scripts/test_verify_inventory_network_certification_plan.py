"""Tests for the isolated inventory network Terraform plan gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = (
    _ROOT / "scripts" / "deployment" / "azure" / "verify_inventory_network_certification_plan.py"
)
_SPEC = importlib.util.spec_from_file_location("verify_inventory_network_certification_plan", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _plan(action: str) -> dict[str, object]:
    return {
        "resource_changes": [
            {"address": address, "change": {"actions": [action]}}
            for address in sorted(_MODULE.EXPECTED_ADDRESSES)
        ]
    }


@pytest.mark.parametrize(("mode", "action"), [("create", "create"), ("cleanup", "delete")])
def test_exact_plan_is_accepted(mode: str, action: str) -> None:
    _MODULE.verify_plan(_plan(action), mode=mode)


def test_unreviewed_address_is_rejected() -> None:
    plan = _plan("create")
    plan["resource_changes"].append(
        {"address": "azurerm_virtual_network.shared", "change": {"actions": ["create"]}}
    )

    with pytest.raises(_MODULE.PlanVerificationError, match="unreviewed"):
        _MODULE.verify_plan(plan, mode="create")


def test_replacement_is_rejected() -> None:
    plan = _plan("create")
    plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]

    with pytest.raises(_MODULE.PlanVerificationError, match="non-create"):
        _MODULE.verify_plan(plan, mode="create")


def test_incomplete_cleanup_is_rejected() -> None:
    plan = _plan("delete")
    plan["resource_changes"].pop()

    with pytest.raises(_MODULE.PlanVerificationError, match="complete reviewed"):
        _MODULE.verify_plan(plan, mode="cleanup")
