#!/usr/bin/env python3
"""Reject a System Knowledge Service plan outside its closed resource boundary."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_PREFIX = "module.system_knowledge_service[0]."
_BASE_ADDRESSES = {
    _PREFIX + "azurerm_role_assignment.acr_pull",
    _PREFIX + "azurerm_role_assignment.claim_writer",
    _PREFIX + "azurerm_role_assignment.principal_map_reader",
    _PREFIX + "azurerm_storage_container.claims",
    _PREFIX + "azurerm_user_assigned_identity.service",
    _PREFIX + "module.container_app.azurerm_container_app.service",
    _PREFIX + "terraform_data.authority_contract",
}
_BOT_ADDRESSES = {
    _PREFIX + "azurerm_bot_channel_ms_teams.service",
    _PREFIX + "azurerm_bot_service_azure_bot.service",
}
_ADDRESSES = _BASE_ADDRESSES | _BOT_ADDRESSES
_CONTAINER = _PREFIX + "module.container_app.azurerm_container_app.service"
_BOT = _PREFIX + "azurerm_bot_service_azure_bot.service"
_CLAIMS = _PREFIX + "azurerm_storage_container.claims"
_ROLES = {
    _PREFIX + "azurerm_role_assignment.acr_pull": "AcrPull",
    _PREFIX + "azurerm_role_assignment.claim_writer": "Storage Blob Data Contributor",
    _PREFIX + "azurerm_role_assignment.principal_map_reader": "Key Vault Secrets User",
}
_AUTHORITY = _PREFIX + "terraform_data.authority_contract"
_IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
_COMMON_ENV = {
    "FDAI_EXECUTION_VENUE",
    "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL",
    "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID",
    "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT",
    "RUNTIME_ENV",
}
_BOT_ENV = {
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL",
    "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON",
}
_OUTGOING_HMAC_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET"
_FORBIDDEN_ENV_PARTS = ("EXECUTOR", "DATABASE", "KAFKA", "LLM", "AZURE_SUBSCRIPTION")


class SystemKnowledgePlanError(ValueError):
    """The plan changes an unapproved resource or runtime capability."""


def validate_plan(
    plan: Mapping[str, Any],
    *,
    transition: str,
    image_ref: str,
    transport: str = "bot_framework",
) -> None:
    """Validate one transport-specific transition without accepting replacements."""

    if (
        transition not in {"bootstrap", "enable", "disable"}
        or transport not in {"bot_framework", "outgoing_webhook"}
        or (transition == "bootstrap" and transport != "outgoing_webhook")
        or _IMAGE.fullmatch(image_ref) is None
    ):
        raise SystemKnowledgePlanError("transition or image reference is invalid")
    expected_addresses = (
        _BASE_ADDRESSES | _BOT_ADDRESSES if transport == "bot_framework" else _BASE_ADDRESSES
    )
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise SystemKnowledgePlanError("plan resource_changes must be an array")
    by_address: dict[str, Mapping[str, Any]] = {}
    for entry in changes:
        if not isinstance(entry, Mapping):
            raise SystemKnowledgePlanError("plan resource change must be an object")
        address = entry.get("address")
        if not isinstance(address, str) or address not in _ADDRESSES or address in by_address:
            raise SystemKnowledgePlanError("plan contains an unknown or duplicate resource")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, Mapping) else None
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            raise SystemKnowledgePlanError("plan resource action is invalid")
        action_set = set(actions)
        if transition == "disable":
            if action_set != {"delete"}:
                raise SystemKnowledgePlanError("disable plan may contain only deletes")
        elif "delete" in action_set or not action_set <= {"create", "read", "update"}:
            raise SystemKnowledgePlanError("enable plan may not replace or delete resources")
        by_address[address] = entry
    if transition in {"bootstrap", "enable"}:
        planned = _planned_resources(plan)
        if not planned:
            planned = {
                address: after
                for address, entry in by_address.items()
                if isinstance((change := entry.get("change")), Mapping)
                and isinstance((after := change.get("after")), Mapping)
            }
        _validate_active(
            planned,
            image_ref=image_ref,
            transport=transport,
            transition=transition,
        )
    elif set(by_address) != expected_addresses:
        raise SystemKnowledgePlanError("disable plan must remove the complete service boundary")


def _validate_active(
    resources: Mapping[str, Mapping[str, Any]],
    *,
    image_ref: str,
    transport: str,
    transition: str,
) -> None:
    expected_addresses = (
        _BASE_ADDRESSES | _BOT_ADDRESSES if transport == "bot_framework" else _BASE_ADDRESSES
    )
    if not expected_addresses <= resources.keys():
        raise SystemKnowledgePlanError("enable plan is missing the complete service boundary")
    if transport == "outgoing_webhook" and _BOT_ADDRESSES & resources.keys():
        raise SystemKnowledgePlanError("Outgoing Webhook plan may not create Azure Bot resources")
    container = resources[_CONTAINER]
    template = _one(container.get("template"), "Container App template")
    primary = _one(template.get("container"), "Container App primary container")
    if (
        primary.get("image") != image_ref
        or primary.get("name") != "system-knowledge-service"
        or template.get("min_replicas") != 1
        or template.get("max_replicas") != 1
    ):
        raise SystemKnowledgePlanError("Container App image or replica contract changed")
    environment = primary.get("env")
    if not isinstance(environment, list):
        raise SystemKnowledgePlanError("Container App environment is invalid")
    names = {
        item.get("name")
        for item in environment
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    expected_env = _COMMON_ENV | (
        _BOT_ENV
        if transport == "bot_framework"
        else ({_OUTGOING_HMAC_ENV} if transition == "enable" else set())
    )
    if names != expected_env or any(
        part in name for name in names for part in _FORBIDDEN_ENV_PARTS
    ):
        raise SystemKnowledgePlanError(
            "Container App environment exceeds read-only knowledge scope"
        )
    identities = _one(container.get("identity"), "Container App identity")
    identity_ids = identities.get("identity_ids")
    if not isinstance(identity_ids, list) or len(identity_ids) != 1:
        raise SystemKnowledgePlanError("Container App must use one dedicated identity")
    claims = resources[_CLAIMS]
    if claims.get("container_access_type") != "private":
        raise SystemKnowledgePlanError("claim container must remain private")
    for address, role in _ROLES.items():
        if resources[address].get("role_definition_name") != role:
            raise SystemKnowledgePlanError("service role assignment exceeds the approved set")
    if transport == "bot_framework":
        bot = resources[_BOT]
        if (
            bot.get("microsoft_app_type") != "UserAssignedMSI"
            or not isinstance(bot.get("microsoft_app_id"), str)
            or not bot.get("microsoft_app_id")
            or not isinstance(bot.get("microsoft_app_msi_id"), str)
            or not bot.get("microsoft_app_msi_id")
            or bot.get("sku") != "F0"
            or bot.get("local_authentication_enabled") is not False
            or bot.get("public_network_access_enabled") is not True
            or not str(bot.get("endpoint", "")).endswith("/api/teams/messages")
        ):
            raise SystemKnowledgePlanError("Azure Bot contract exceeds the approved boundary")
    authority = resources[_AUTHORITY]
    input_value = authority.get("input")
    if (
        not isinstance(input_value, Mapping)
        or input_value.get("execution_authority") is not False
        or input_value.get("replica_ceiling") != 1
        or input_value.get("teams_transport") != transport
    ):
        raise SystemKnowledgePlanError("service authority contract is invalid")


def _planned_resources(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    planned = plan.get("planned_values")
    root = planned.get("root_module") if isinstance(planned, Mapping) else None
    if not isinstance(root, Mapping):
        return {}
    resources: dict[str, Mapping[str, Any]] = {}

    def visit(module: Mapping[str, Any]) -> None:
        values = module.get("resources", [])
        children = module.get("child_modules", [])
        if not isinstance(values, list) or not isinstance(children, list):
            raise SystemKnowledgePlanError("planned module resources are invalid")
        for item in values:
            address = item.get("address") if isinstance(item, Mapping) else None
            value = item.get("values") if isinstance(item, Mapping) else None
            if not isinstance(address, str) or not isinstance(value, Mapping):
                raise SystemKnowledgePlanError("planned resource is invalid")
            if address in resources:
                raise SystemKnowledgePlanError("planned resource address is duplicated")
            resources[address] = value
        for child in children:
            if not isinstance(child, Mapping):
                raise SystemKnowledgePlanError("planned child module is invalid")
            visit(child)

    visit(root)
    return resources


def _one(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        raise SystemKnowledgePlanError(f"{label} must contain exactly one object")
    return value[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument(
        "--transition",
        choices=("bootstrap", "enable", "disable"),
        required=True,
    )
    parser.add_argument(
        "--transport",
        choices=("bot_framework", "outgoing_webhook"),
        required=True,
    )
    parser.add_argument("--image-ref", required=True)
    arguments = parser.parse_args()
    plan = json.loads(arguments.plan_json.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SystemKnowledgePlanError("plan must be a JSON object")
    validate_plan(
        plan,
        transition=arguments.transition,
        image_ref=arguments.image_ref,
        transport=arguments.transport,
    )
    print("system-knowledge-plan: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
