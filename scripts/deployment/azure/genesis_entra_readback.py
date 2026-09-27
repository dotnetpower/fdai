#!/usr/bin/env python3
"""Independent complete readback for the bounded Entra app/group plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from genesis_entra import (
    _GROUP_SLOTS,
    _GUID,
    EntraPlan,
    _az_json,
    _directory_inventory,
    _graph,
    _verify_role_group_inventory,
    plan_entra,
    read_entra_bindings,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class EntraEffectReadback:
    """Private complete effect evidence plus a sanitized terminal projection."""

    bindings: dict[str, str]
    evidence_digest: str

    def projection(self) -> dict[str, object]:
        return {
            "applications_verified": True,
            "service_principals_verified": True,
            "role_and_scope_definitions_verified": True,
            "group_role_assignments_verified": True,
            "owner_membership_changed_by_operation": False,
            "runner_spa_ownership_granted_by_operation": False,
            "graph_application_readwrite_ownedby_granted_by_operation": False,
            "provider_admin_consent_granted_by_operation": False,
            "readback_digest": self.evidence_digest,
        }


def read_entra_effects(
    *,
    plan: EntraPlan,
) -> EntraEffectReadback:
    """Verify apps, principals, definitions, and five existing-group assignments."""

    if (
        plan.configure_roles is not True
        or plan.configure_runner_graph is not False
        or _DIGEST.fullmatch(plan.digest) is None
    ):
        raise ValueError("bounded Entra readback context is invalid")
    if len(plan.role_groups) != 5:
        raise ValueError("bounded Entra role-group binding is incomplete")
    post_plan = plan_entra(
        bounded=True,
        approved_role_groups=dict(plan.role_groups),
    )
    if post_plan.create_apps or post_plan.create_groups:
        raise ValueError("bounded Entra object readback is incomplete")
    bindings = read_entra_bindings()
    apps, groups_by_name = _directory_inventory()
    api_app = apps["fdai-api"]
    spa_app = apps["fdai-console-spa"]
    approval_bot_app = apps["fdai-approval-bot"]
    if api_app is None or spa_app is None or approval_bot_app is None:
        raise ValueError("Entra application readback is incomplete")
    _verify_role_group_inventory(groups_by_name, plan.role_groups)
    principals = {
        name: _read_service_principal(str(app["appId"]))
        for name, app in (
            ("api", api_app),
            ("spa", spa_app),
            ("approval_bot", approval_bot_app),
        )
    }
    if len({str(value["id"]) for value in principals.values()}) != 3:
        raise ValueError("Entra service principal readback is ambiguous")
    api_sp = principals["api"]
    roles = {
        str(item["value"]): str(item["id"])
        for item in api_app.get("appRoles", [])
        if isinstance(item, dict) and item.get("isEnabled") is True
    }
    assignments_value = _graph("GET", f"servicePrincipals/{api_sp['id']}/appRoleAssignedTo")
    assignments = assignments_value.get("value") if isinstance(assignments_value, dict) else None
    if not isinstance(assignments, list) or any(not isinstance(row, dict) for row in assignments):
        raise ValueError("Entra App Role assignment readback is invalid")
    verified_assignments: list[tuple[str, str]] = []
    approved_groups = dict(plan.role_groups)
    for slot, (_variable, _display_name, role) in _GROUP_SLOTS.items():
        if role not in roles:
            raise ValueError("Entra role group readback is incomplete")
        group_id = approved_groups[slot]
        matches = [
            row
            for row in assignments
            if row.get("principalId") == group_id
            and row.get("resourceId") == api_sp["id"]
            and row.get("appRoleId") == roles[role]
            and row.get("principalType") == "Group"
        ]
        if len(matches) != 1:
            raise ValueError("Entra group App Role assignment readback is incomplete")
        verified_assignments.append((group_id, roles[role]))
    evidence = {
        "plan_digest": plan.digest,
        "bindings": bindings,
        "service_principals": {name: str(value["id"]) for name, value in principals.items()},
        "assignments": sorted(verified_assignments),
    }
    return EntraEffectReadback(bindings=bindings, evidence_digest=canonical_digest(evidence))


def _read_service_principal(app_id: str) -> dict[str, Any]:
    values = _az_json(("ad", "sp", "list", "--filter", f"appId eq '{app_id}'"))
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], dict)
        or values[0].get("appId") != app_id
        or _GUID.fullmatch(str(values[0].get("id", ""))) is None
    ):
        raise ValueError("Entra service principal readback is incomplete")
    return values[0]
