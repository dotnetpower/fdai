"""Synthetic exact-plan and Azure SKU restriction regressions; no live provider calls."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_skus import (  # noqa: E402
    EVIDENCE_INVALID,
    PLAN_INVALID,
    SKU_RESTRICTED,
    image_vm_selections,
    load_sku_json,
    require_sku_eligibility,
)


def plan() -> dict[str, Any]:
    return {
        "format_version": "1.2",
        "complete": True,
        "errored": False,
        "applyable": True,
        "resource_changes": [
            {
                "address": f"azurerm_linux_virtual_machine.{role}",
                "mode": "managed",
                "type": "azurerm_linux_virtual_machine",
                "change": {
                    "actions": ["create"],
                    "after": {"size": size, "location": "eastus", "zone": None},
                    "after_unknown": {},
                },
            }
            for role, size in (("builder", "Standard_D2ds_v5"), ("verifier", "Standard_B2s"))
        ],
    }


def rows() -> list[dict[str, Any]]:
    return [
        {
            "resourceType": "virtualMachines",
            "name": size,
            "locations": ["EastUS"],
            "locationInfo": [{"location": "EASTUS", "zones": ["1", "2", "3"]}],
            "restrictions": [],
        }
        for size in ("Standard_D2ds_v5", "Standard_B2s")
    ]


def restriction(kind: str = "Location", *, location: str = "EastUS") -> dict[str, Any]:
    return {
        "type": kind,
        "values": [location],
        "restrictionInfo": {"locations": [location], "zones": ["1", "2"]},
        "reasonCode": "NotAvailableForSubscription",
    }


def test_exact_selections_preserve_nondefault_sizes_and_normalize_location_only() -> None:
    value = plan()
    value["resource_changes"][0]["change"]["after"]["size"] = "Standard_D2s_v5"
    value["resource_changes"][0]["change"]["after"]["location"] = "EastUS"
    value["resource_changes"].append(
        {"address": "azurerm_virtual_network.builder", "type": "azurerm_virtual_network"}
    )
    before = copy.deepcopy(value)
    selected = image_vm_selections(json.dumps(value).encode(), region="EASTUS")
    assert [(item.size, item.region, item.zone) for item in selected] == [
        ("Standard_D2s_v5", "eastus", None),
        ("Standard_B2s", "eastus", None),
    ]
    assert value == before


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("format_version", []),
        ("format_version", "2.0"),
        ("complete", 1),
        ("complete", False),
        ("errored", 0),
        ("errored", True),
        ("applyable", 1),
        ("applyable", False),
        ("deferred_changes", [{}]),
        ("resource_changes", None),
        ("resource_changes", []),
        ("resource_changes", [None, None]),
        ("resource_changes", [{}] * 129),
    ],
)
def test_incomplete_plan_is_rejected(key: str, value: object) -> None:
    candidate = plan()
    candidate[key] = value
    with pytest.raises(CheckError, match=f"^{PLAN_INVALID}$"):
        image_vm_selections(json.dumps(candidate).encode(), region="eastus")


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\xff", b'{"complete":true,"complete":false}'])
def test_invalid_json_never_exposes_plan_content(raw: bytes) -> None:
    with pytest.raises(CheckError, match=f"^{PLAN_INVALID}$"):
        image_vm_selections(raw, region="eastus")


@pytest.mark.parametrize("field", ["size", "location", "zone"])
@pytest.mark.parametrize("unknown", [True, None, [], 0])
def test_unknown_vm_selection_never_defaults_to_eligible(field: str, unknown: object) -> None:
    candidate = plan()
    candidate["resource_changes"][0]["change"]["after_unknown"][field] = unknown
    with pytest.raises(CheckError, match=PLAN_INVALID):
        image_vm_selections(json.dumps(candidate).encode(), region="eastus")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size", None),
        ("size", "Standard_D2s_v5' || @"),
        ("size", "--different-target"),
        ("location", "westus"),
        ("location", None),
        ("zone", True),
        ("zone", 1),
        ("zone", ""),
        ("zone", "0"),
    ],
)
def test_invalid_resolved_selection_fails_closed(field: str, value: object) -> None:
    candidate = plan()
    candidate["resource_changes"][0]["change"]["after"][field] = value
    with pytest.raises(CheckError, match=PLAN_INVALID):
        image_vm_selections(json.dumps(candidate).encode(), region="eastus")


@pytest.mark.parametrize(
    "change",
    [
        {"address": None},
        {"address": "azurerm_linux_virtual_machine.other"},
        {"type": "unexpected"},
        {"mode": "data"},
        {"change": None},
        {"change": {"actions": ["no-op"], "after": {}}},
        {"change": {"actions": ["create"], "after": None}},
        {"change": {"actions": ["create"], "after": {}, "after_unknown": True}},
    ],
)
def test_vm_address_shape_and_create_action_are_required(change: dict[str, object]) -> None:
    candidate = plan()
    candidate["resource_changes"][0].update(change)
    with pytest.raises(CheckError, match=PLAN_INVALID):
        image_vm_selections(json.dumps(candidate).encode(), region="eastus")


@pytest.mark.parametrize("duplicate", [True, False])
def test_both_unique_vm_roles_are_required(duplicate: bool) -> None:
    candidate = plan()
    if duplicate:
        candidate["resource_changes"][1] = candidate["resource_changes"][0]
    else:
        candidate["resource_changes"][1] = {"address": "data.other", "type": "other"}
    with pytest.raises(CheckError, match=PLAN_INVALID):
        image_vm_selections(json.dumps(candidate).encode(), region="eastus")


def test_complete_unrestricted_evidence_is_not_modified() -> None:
    evidence = rows()
    before = copy.deepcopy(evidence)
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    assert require_sku_eligibility(selected, evidence) is None
    assert evidence == before


@pytest.mark.parametrize("role_index", [0, 1])
@pytest.mark.parametrize("reason", ["NotAvailableForSubscription", "QuotaId"])
def test_either_regionally_restricted_vm_blocks(role_index: int, reason: str) -> None:
    evidence = rows()
    item = restriction()
    item["reasonCode"] = reason
    evidence[role_index]["restrictions"] = [item]
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    with pytest.raises(CheckError, match=f"^{SKU_RESTRICTED}$") as error:
        require_sku_eligibility(selected, evidence)
    assert error.value.exit_code == 3


@pytest.mark.parametrize("zone", [None, "1", "3"])
def test_zone_restriction_uses_explicit_scope_not_generic_values(zone: str | None) -> None:
    candidate = plan()
    candidate["resource_changes"][0]["change"]["after"]["zone"] = zone
    evidence = rows()
    evidence[0]["restrictions"] = [restriction("Zone")]
    selected = image_vm_selections(json.dumps(candidate).encode(), region="eastus")
    if zone == "1":
        with pytest.raises(CheckError, match=SKU_RESTRICTED):
            require_sku_eligibility(selected, evidence)
    else:
        require_sku_eligibility(selected, evidence)


def test_restriction_in_another_region_does_not_block_exact_selection() -> None:
    evidence = rows()
    evidence[0]["restrictions"] = [
        restriction(location="WestUS"),
        restriction("Zone", location="WestUS"),
    ]
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    require_sku_eligibility(selected, evidence)


@pytest.mark.parametrize("removed", ["restrictionInfo", "values"])
def test_location_restriction_accepts_each_documented_location_source(removed: str) -> None:
    evidence = rows()
    item = restriction()
    item.pop(removed)
    evidence[0]["restrictions"] = [item]
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    with pytest.raises(CheckError, match=SKU_RESTRICTED):
        require_sku_eligibility(selected, evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Standard_other"),
        ("name", []),
        ("resourceType", "disks"),
        ("locations", []),
        ("locations", ["EastUS"] * 65),
        ("locations", [None]),
        ("locations", ["westus"]),
        ("locations", "eastus"),
        ("restrictions", None),
        ("restrictions", {}),
        ("restrictions", [{}] * 65),
        ("restrictions", [None]),
        ("restrictions", [{"reasonCode": []}]),
        ("restrictions", [{"reasonCode": "unexpected"}]),
        ("restrictions", [{**restriction(), "type": "unexpected"}]),
        ("restrictions", [{**restriction(), "restrictionInfo": []}]),
        ("restrictions", [{**restriction(), "values": ["westus"]}]),
        ("restrictions", [{**restriction("Zone"), "restrictionInfo": {"locations": ["EastUS"]}}]),
    ],
)
def test_malformed_provider_evidence_is_unknown_not_eligible(field: str, value: object) -> None:
    evidence = rows()
    evidence[0][field] = value
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    with pytest.raises(CheckError, match=f"^{EVIDENCE_INVALID}$"):
        require_sku_eligibility(selected, evidence)


@pytest.mark.parametrize("evidence", [[], [None], [*rows(), rows()[0]]])
def test_missing_or_duplicate_sku_cannot_be_complete(evidence: list[object]) -> None:
    selected = image_vm_selections(json.dumps(plan()).encode(), region="eastus")
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        require_sku_eligibility(selected, evidence)


@pytest.mark.parametrize(
    "info",
    [
        None,
        [],
        [None],
        [{"location": None}],
        [{"location": "westus", "zones": ["1"]}],
        [{"location": "EastUS", "zones": []}],
        [{"location": "EastUS", "zones": [True]}],
        [{"location": "EastUS", "zones": ["2"]}],
        [{"location": "EastUS", "zones": ["1"]}] * 2,
    ],
)
def test_explicit_zone_requires_unique_positive_offering_evidence(info: object) -> None:
    candidate = plan()
    candidate["resource_changes"][0]["change"]["after"]["zone"] = "1"
    evidence = rows()
    evidence[0]["locationInfo"] = info
    selected = image_vm_selections(json.dumps(candidate).encode(), region="eastus")
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        require_sku_eligibility(selected, evidence)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'{"value":{},"value":{}}',
        b'{"value":{"restrictions":[1],"restrictions":[]}}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_evidence_json_rejects_nonfinite_duplicate_and_excessively_nested_values(
    raw: bytes,
) -> None:
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        load_sku_json(raw, max_bytes=8192)
