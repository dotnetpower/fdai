#!/usr/bin/env python3
"""Filter exact reviewed platform migrations from a temporary plan review copy."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ROLE_REPLACEMENTS = {
    "azurerm_role_assignment.dev_gateway_storage_deployer[0]": (
        "principal_id",
        "Storage Blob Data Contributor",
    ),
    "azurerm_role_assignment.ingestion_eventhubs_sender[0]": (
        "scope",
        "Azure Event Hubs Data Sender",
    ),
    "azurerm_role_assignment.ingestion_worker_eventhubs_sender[0]": (
        "scope",
        "Azure Event Hubs Data Sender",
    ),
    "azurerm_role_assignment.kv_officer_self": (
        "principal_id",
        "Key Vault Secrets Officer",
    ),
    "azurerm_role_assignment.operator_api_acr_pull[0]": (
        "principal_id",
        "AcrPull",
    ),
    "azurerm_role_assignment.operator_api_kv_secrets_user[0]": (
        "principal_id",
        "Key Vault Secrets User",
    ),
    "azurerm_role_assignment.operator_api_reader[0]": (
        "principal_id",
        "Reader",
    ),
    "module.case_history_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "principal_id",
        "Storage Blob Data Owner",
    ),
    "module.document_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "principal_id",
        "Storage Blob Data Owner",
    ),
}
_MEASUREMENT_RETIREMENTS = {
    "module.measurement_runners[0].azurerm_container_app_job.baseline_regression[0]": (
        "baseline_regression"
    ),
    "module.measurement_runners[0].azurerm_container_app_job.pattern_growth[0]": "pattern_growth",
}
_EMBEDDING_ADDRESS = (
    'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.embedding"]'
)


def filter_reviewed_platform_migrations(
    plan: object,
    *,
    expected_deploy_principal_id: str,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Validate and remove only the reviewed migration changes."""

    if _GUID.fullmatch(expected_deploy_principal_id) is None:
        raise ValueError("expected deploy principal id must be a GUID")
    if not isinstance(plan, Mapping):
        raise ValueError("protected Terraform plan MUST be an object")
    raw_changes = plan.get("resource_changes")
    if not isinstance(raw_changes, list):
        raise ValueError("protected Terraform plan resource_changes MUST be an array")
    changes: list[Mapping[str, object]] = []
    by_address: dict[str, Mapping[str, object]] = {}
    for raw_change in raw_changes:
        if not isinstance(raw_change, Mapping):
            raise ValueError("protected Terraform resource changes MUST be objects")
        address = raw_change.get("address")
        if not isinstance(address, str) or not address:
            raise ValueError("protected Terraform resource address is invalid")
        if address in by_address:
            raise ValueError("protected Terraform plan has duplicate resource addresses")
        changes.append(raw_change)
        by_address[address] = raw_change

    validated: set[str] = set()
    for address, (replacement_field, role_name) in _ROLE_REPLACEMENTS.items():
        change = by_address.get(address)
        if change is None:
            continue
        if not _exact_role_replacement(
            change,
            replacement_field=replacement_field,
            role_name=role_name,
            expected_deploy_principal_id=expected_deploy_principal_id,
        ):
            raise ValueError(f"unapproved platform role replacement: {address}")
        validated.add(address)

    for retired, resource_name in _MEASUREMENT_RETIREMENTS.items():
        change = by_address.get(retired)
        if change is None:
            continue
        if not _exact_measurement_retirement(change, resource_name=resource_name):
            raise ValueError(f"unapproved measurement runner retirement: {retired}")
        validated.add(retired)

    embedding = by_address.get(_EMBEDDING_ADDRESS)
    if embedding is not None and "delete" in _actions(embedding):
        if not _exact_embedding_replacement(embedding):
            raise ValueError("unapproved t1.embedding replacement")
        validated.add(_EMBEDDING_ADDRESS)

    copied = dict(plan)
    copied["resource_changes"] = [
        change for change in changes if str(change.get("address")) not in validated
    ]
    return copied, tuple(sorted(validated))


def _exact_role_replacement(
    change: Mapping[str, object],
    *,
    replacement_field: str,
    role_name: str,
    expected_deploy_principal_id: str,
) -> bool:
    details = change.get("change")
    if not isinstance(details, Mapping):
        return False
    before = details.get("before")
    after = details.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return False
    stable_field = "scope" if replacement_field == "principal_id" else "principal_id"
    return (
        _actions(change) == ("delete", "create")
        and details.get("replace_paths") == [[replacement_field]]
        and before.get("role_definition_name") == after.get("role_definition_name") == role_name
        and _nonempty(before.get(stable_field))
        and before.get(stable_field) == after.get(stable_field)
        and _nonempty(before.get(replacement_field))
        and before.get(replacement_field) != after.get(replacement_field)
        and (
            replacement_field != "principal_id"
            or str(after.get("principal_id", "")).casefold()
            == expected_deploy_principal_id.casefold()
        )
    )


def _exact_embedding_replacement(change: Mapping[str, object]) -> bool:
    details = change.get("change")
    if not isinstance(details, Mapping):
        return False
    before = details.get("before")
    after = details.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return False
    before_model = _single_block(before, "model")
    after_model = _single_block(after, "model")
    before_sku = _single_block(before, "sku")
    after_sku = _single_block(after, "sku")
    return (
        _actions(change) == ("delete", "create")
        and before.get("name") == after.get("name") == "t1.embedding"
        and _nonempty(before.get("cognitive_account_id"))
        and before.get("cognitive_account_id") == after.get("cognitive_account_id")
        and before_model is not None
        and after_model is not None
        and before_model.get("format") == after_model.get("format") == "OpenAI"
        and before_model.get("name") == "text-embedding-3-small"
        and after_model.get("name") == "text-embedding-3-large"
        and before_model.get("version") == after_model.get("version") == "1"
        and before_sku is not None
        and after_sku is not None
        and before_sku.get("name") == "GlobalStandard"
        and before_sku.get("capacity") == 803
        and after_sku.get("name") == "Standard"
        and after_sku.get("capacity") == 200
    )


def _exact_measurement_retirement(
    change: Mapping[str, object],
    *,
    resource_name: str,
) -> bool:
    details = change.get("change")
    if not isinstance(details, Mapping):
        return False
    before = details.get("before")
    return (
        change.get("mode") == "managed"
        and change.get("type") == "azurerm_container_app_job"
        and change.get("name") == resource_name
        and change.get("index") == 0
        and _actions(change) == ("delete",)
        and isinstance(before, Mapping)
        and details.get("after") is None
        and not details.get("replace_paths")
    )


def _actions(change: object) -> tuple[object, ...]:
    if not isinstance(change, Mapping):
        return ()
    details = change.get("change")
    if not isinstance(details, Mapping):
        return ()
    actions = details.get("actions")
    return tuple(actions) if isinstance(actions, list) else ()


def _single_block(value: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    blocks = value.get(key)
    if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], Mapping):
        return None
    return blocks[0]


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        filtered, validated = filter_reviewed_platform_migrations(
            plan,
            expected_deploy_principal_id=os.environ.get("DEPLOY_RUNNER_PRINCIPAL_ID", ""),
        )
    except ValueError as error:
        print(str(error))
        return 1
    args.plan.write_text(
        json.dumps(filtered, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    for address in validated:
        print(f"Protected plan permits reviewed migration: {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
