#!/usr/bin/env python3
"""Verify the exact create or cleanup plan for the inventory network sandbox."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAX_PLAN_BYTES = 8 * 1024 * 1024
EXPECTED_ADDRESSES = frozenset(
    {
        "azurerm_container_app_environment.certification",
        "azurerm_container_app_job.campaign",
        "azurerm_container_app_job.migrate",
        "azurerm_container_app_job.verifier",
        "azurerm_log_analytics_workspace.certification",
        "azurerm_monitor_diagnostic_setting.receipt_blob",
        "azurerm_network_security_group.certification",
        "azurerm_postgresql_flexible_server.certification",
        "azurerm_postgresql_flexible_server_configuration.connection_throttle",
        "azurerm_postgresql_flexible_server_configuration.log_checkpoints",
        "azurerm_postgresql_flexible_server_configuration.log_connections",
        "azurerm_postgresql_flexible_server_configuration.tls_floor",
        "azurerm_postgresql_flexible_server_database.certification",
        "azurerm_private_dns_zone.blob",
        "azurerm_private_dns_zone.postgres",
        "azurerm_private_dns_zone_virtual_network_link.blob",
        "azurerm_private_dns_zone_virtual_network_link.postgres",
        "azurerm_private_endpoint.blob",
        "azurerm_resource_group.certification",
        "azurerm_role_assignment.campaign_acr_pull",
        "azurerm_role_assignment.campaign_receipt_writer",
        "azurerm_role_assignment.campaign_subscription_reader",
        "azurerm_role_assignment.verifier_acr_pull",
        "azurerm_role_assignment.verifier_receipt_reader",
        "azurerm_role_assignment.verifier_sandbox_reader",
        "azurerm_storage_account.receipts",
        "azurerm_storage_container.receipts",
        "azurerm_subnet.container_apps",
        "azurerm_subnet_network_security_group_association.container_apps",
        "azurerm_subnet_network_security_group_association.postgres",
        "azurerm_subnet_network_security_group_association.private_endpoints",
        "azurerm_subnet.postgres",
        "azurerm_subnet.private_endpoints",
        "azurerm_user_assigned_identity.campaign",
        "azurerm_user_assigned_identity.verifier",
        "azurerm_virtual_network.certification",
        "random_password.postgres",
        "terraform_data.target_fence",
    }
)


class PlanVerificationError(ValueError):
    """Report a fail-closed plan-shape violation without exposing plan values."""


def load_plan(path: Path) -> dict[str, Any]:
    """Load one bounded Terraform JSON plan from a regular file."""

    if not path.is_file() or path.is_symlink():
        raise PlanVerificationError("plan JSON must be a regular non-symlink file")
    if path.stat().st_size > MAX_PLAN_BYTES:
        raise PlanVerificationError("plan JSON exceeds the 8 MiB verification limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanVerificationError("plan JSON is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise PlanVerificationError("plan JSON root must be an object")
    return value


def verify_plan(plan: dict[str, Any], *, mode: str) -> None:
    """Require the complete reviewed address set and one exact action."""

    expected_action = ["create"] if mode == "create" else ["delete"]
    resource_changes = plan.get("resource_changes")
    if not isinstance(resource_changes, list):
        raise PlanVerificationError("plan JSON must contain resource_changes")
    observed: set[str] = set()
    for item in resource_changes:
        if not isinstance(item, dict):
            raise PlanVerificationError("resource_changes entries must be objects")
        address = item.get("address")
        change = item.get("change")
        if not isinstance(address, str) or not isinstance(change, dict):
            raise PlanVerificationError("resource change identity is malformed")
        actions = change.get("actions")
        if actions in (["no-op"], ["read"]):
            continue
        if address in observed:
            raise PlanVerificationError("plan contains a duplicate changed address")
        observed.add(address)
        if address not in EXPECTED_ADDRESSES:
            raise PlanVerificationError("plan changes an unreviewed address")
        if actions != expected_action:
            raise PlanVerificationError(f"{mode} plan contains a non-{expected_action[0]} action")
    if observed != EXPECTED_ADDRESSES:
        raise PlanVerificationError("plan does not contain the complete reviewed address set")


def main(argv: list[str] | None = None) -> int:
    """Validate one plan and emit only a value-free action count."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "cleanup"))
    parser.add_argument("plan_json", type=Path)
    args = parser.parse_args(argv)
    try:
        verify_plan(load_plan(args.plan_json), mode=args.mode)
    except PlanVerificationError as exc:
        print(f"INVENTORY_NETWORK_PLAN_BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print(f"INVENTORY_NETWORK_PLAN_OK mode={args.mode} count={len(EXPECTED_ADDRESSES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
