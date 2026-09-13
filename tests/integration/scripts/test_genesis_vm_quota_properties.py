"""Exhaustive small quota boundaries for three roles, without assuming missing usage is zero."""

from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_vm_sku_choice import choose_deployment_vms  # noqa: E402
from tests.integration.scripts.test_genesis_vm_sku_choice import (  # noqa: E402
    policy,
    rows,
    sku,
    usages,
)


@pytest.mark.parametrize("regional,dd,b", list(product([7, 8, 9], [5, 6, 7, 8], [0, 1, 2])))
def test_three_role_quota_never_counts_family_budgets_independently(regional, dd, b):
    catalog = [*rows(), sku("Standard_B2s", memory=4, family="standardBSFamily")]
    quota = [
        {"name": "cores", "current": 10, "limit": 10 + regional},
        {"name": "standardDDSv4Family", "current": 2, "limit": 2 + dd},
        {"name": "standardBSFamily", "current": 1, "limit": 1 + b},
    ]
    possible = regional >= 8 and (dd >= 8 or (dd >= 6 and b >= 2))
    if not possible:
        with pytest.raises(CheckError, match="combined_quota_insufficient"):
            choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=quota)
        return
    selected = choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=quota)
    assert selected.builder.vcpus + selected.verifier.vcpus + selected.foundation.vcpus == 8
    assert selected.verifier.size == ("Standard_B2s" if b >= 2 else "Standard_D2ds_v4")
    assert (
        choose_deployment_vms(policy(), region="eastus", rows=catalog[::-1], usages=quota[::-1])
        == selected
    )


@pytest.mark.parametrize("fault", ["missing", "duplicate", "negative", "boolean"])
def test_unknown_family_quota_cannot_be_replaced_by_zero(fault):
    quota = usages()
    if fault == "missing":
        quota.pop()
    elif fault == "duplicate":
        quota.append({**quota[1], "name": quota[1]["name"].upper()})
    else:
        quota[1]["limit"] = -1 if fault == "negative" else True
    with pytest.raises(CheckError, match="evidence_incomplete"):
        choose_deployment_vms(policy(), region="eastus", rows=rows(), usages=quota)
