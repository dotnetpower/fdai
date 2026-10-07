#!/usr/bin/env python3
"""Resolve production Terraform roots and pre-refresh planning inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from service_contract import (
    ServiceContract,
    ServiceContractError,
    load_matrix,
    resolve_service,
    validate_image_reference,
)


class DriftContractError(ValueError):
    """Raised when drift coverage or stored desired state is incomplete."""


_COST_PSEUDONYM_KEY_ADDRESS = "azurerm_key_vault_secret.cost_pseudonym_key[0]"
_PLATFORM_DATABASE_ADDRESS = "module.state_store.azurerm_postgresql_flexible_server.primary"
_PLATFORM_OPERATOR_IDENTITY_ADDRESS = (
    "module.operator_api_identity[0].azurerm_user_assigned_identity.primary"
)
_POSTGRES_SERVER_ID = re.compile(
    r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/resourceGroups/[A-Za-z0-9._()-]{1,90}"
    r"/providers/Microsoft\.DBforPostgreSQL/flexibleServers/[a-z0-9][a-z0-9-]{1,61}[a-z0-9]",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DriftRoot:
    """Describe one production Terraform state root covered by drift checks."""

    root_id: str
    kind: str
    terraform_root: str
    backend_key: str


def production_roots(environment: str) -> tuple[DriftRoot, ...]:
    """Return the legacy, bootstrap, and five service roots in stable order."""
    service_names = sorted(load_matrix()["services"])
    services = tuple(
        DriftRoot(
            root_id=f"service:{service}",
            kind="service",
            terraform_root=contract.terraform_root,
            backend_key=contract.backend_key,
        )
        for service in service_names
        for contract in (resolve_service(service, environment),)
    )
    return (
        DriftRoot(
            root_id="legacy",
            kind="legacy",
            terraform_root="infra",
            backend_key=f"fdai-{environment}.tfstate",
        ),
        DriftRoot(
            root_id="bootstrap",
            kind="bootstrap",
            terraform_root="infra/bootstrap",
            backend_key=f"ops/bootstrap/{environment}.tfstate",
        ),
        *services,
    )


def stored_service_image(
    payload: dict[str, Any],
    *,
    contract: ServiceContract,
    repository: str,
) -> str:
    """Read one digest-pinned primary image from pre-refresh Terraform state JSON."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise DriftContractError("Terraform state JSON has no root module")
    resource = _resource_at_address(root, contract.allowed_resource_address)
    resource_values = resource.get("values")
    if not isinstance(resource_values, dict):
        raise DriftContractError("service resource has no stored values")
    images: list[str] = []
    for image in _container_images(resource_values):
        try:
            validate_image_reference(contract, repository, image)
        except ServiceContractError:
            continue
        images.append(image)
    if len(images) != 1:
        raise DriftContractError("service state must contain exactly one primary image")
    return images[0]


def stored_bootstrap_inputs(payload: dict[str, Any]) -> dict[str, str]:
    """Read required bootstrap plan inputs from pre-refresh Terraform state JSON."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise DriftContractError("Terraform state JSON has no root module")
    app_resource_group = _resource_at_address(root, "data.azurerm_resource_group.app[0]")
    runner = _resource_at_address(root, "azurerm_linux_virtual_machine.runner[0]")
    app_values = app_resource_group.get("values")
    runner_values = runner.get("values")
    app_name = app_values.get("name") if isinstance(app_values, dict) else None
    ssh_keys = runner_values.get("admin_ssh_key") if isinstance(runner_values, dict) else None
    public_keys: list[str] = []
    if isinstance(ssh_keys, list):
        for entry in ssh_keys:
            public_key = entry.get("public_key") if isinstance(entry, dict) else None
            if isinstance(public_key, str):
                public_keys.append(public_key)
    if not isinstance(app_name, str) or not app_name or len(public_keys) != 1:
        raise DriftContractError("bootstrap state is missing required plan inputs")
    if "\n" in public_keys[0]:
        raise DriftContractError("bootstrap SSH public key must be one line")
    return {
        "app_resource_group_name": app_name,
        "runner_ssh_public_key": public_keys[0],
    }


def stored_platform_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    """Read service planning inputs from pre-refresh platform state JSON."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise DriftContractError("Terraform state JSON has no root module")
    resources: dict[str, tuple[str, str, str | None]] = {
        "database_host": (
            "module.state_store.azurerm_postgresql_flexible_server.primary",
            "fqdn",
            None,
        ),
        "event_topic": (
            'module.event_bus.azurerm_eventhub.topic["fdai.change.events"]',
            "name",
            "fdai.change.events",
        ),
        "pipeline_stage_topic": (
            'module.event_bus.azurerm_eventhub.auxiliary["fdai.pipeline.stages"]',
            "name",
            "fdai.pipeline.stages",
        ),
        "pantheon_object_topic": (
            'module.event_bus.azurerm_eventhub.topic["fdai.pantheon.objects"]',
            "name",
            "fdai.pantheon.objects",
        ),
    }
    resolved: dict[str, Any] = {}
    for key, (address, attribute, expected) in resources.items():
        resource = _resource_at_address(root, address)
        resource_values = resource.get("values")
        value = resource_values.get(attribute) if isinstance(resource_values, dict) else None
        if not isinstance(value, str) or not value or "\n" in value:
            raise DriftContractError(f"platform state is missing required {key}")
        if expected is not None and value != expected:
            raise DriftContractError(f"platform state has unexpected {key}")
        resolved[key] = value
    model_endpoints: dict[str, str] = {}
    for address, reference_prefix, hostname_suffix, required in (
        (
            "module.llm_azure_openai[0].azurerm_cognitive_account.primary",
            "azure-openai:",
            ".openai.azure.com",
            True,
        ),
        (
            "module.llm_foundry_partner[0].azurerm_cognitive_account.partner",
            "azure-foundry:",
            ".services.ai.azure.com",
            False,
        ),
    ):
        try:
            resource = _resource_at_address(root, address)
        except LookupError:
            if required:
                raise DriftContractError(
                    "platform state is missing the primary model account"
                ) from None
            continue
        resource_values = resource.get("values")
        name = resource_values.get("name") if isinstance(resource_values, dict) else None
        endpoint = resource_values.get("endpoint") if isinstance(resource_values, dict) else None
        expected_endpoint = (
            f"https://{name}{hostname_suffix}" if isinstance(name, str) and name else None
        )
        if not isinstance(endpoint, str) or endpoint.rstrip("/").lower() != expected_endpoint:
            raise DriftContractError("platform state contains an invalid model endpoint")
        model_endpoints[f"{reference_prefix}{name}"] = endpoint.rstrip("/")
    resolved["model_endpoints"] = dict(sorted(model_endpoints.items()))
    resolved["cost_pseudonym_key_secret_id"] = _stored_cost_pseudonym_key_secret_id(root)
    return resolved


def stored_platform_database(payload: dict[str, Any]) -> dict[str, str]:
    """Read the platform PostgreSQL server identity from pre-refresh platform state JSON."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise DriftContractError("Terraform state JSON has no root module")
    try:
        resource = _resource_at_address(root, _PLATFORM_DATABASE_ADDRESS)
    except LookupError:
        raise DriftContractError("platform state is missing the PostgreSQL server") from None
    resource_values = resource.get("values")
    server_id = resource_values.get("id") if isinstance(resource_values, dict) else None
    if not isinstance(server_id, str) or _POSTGRES_SERVER_ID.fullmatch(server_id) is None:
        raise DriftContractError("platform state contains an invalid PostgreSQL server id")
    return {"server_id": server_id}


def stored_platform_operator_identity(payload: dict[str, Any]) -> dict[str, str]:
    """Read the tracked legacy Operator identity without relying on root outputs."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise DriftContractError("Terraform state JSON has no root module")
    try:
        resource = _resource_at_address(root, _PLATFORM_OPERATOR_IDENTITY_ADDRESS)
    except LookupError:
        raise DriftContractError("platform state is missing the Operator identity") from None
    resource_values = resource.get("values")
    principal_id = (
        resource_values.get("principal_id") if isinstance(resource_values, dict) else None
    )
    if not isinstance(principal_id, str) or not principal_id or "\n" in principal_id:
        raise DriftContractError("platform state contains an invalid Operator identity")
    return {"principal_id": principal_id}


def stored_platform_output_inputs(
    payload: dict[str, Any],
    *,
    resolved_models: dict[str, Any],
) -> dict[str, Any]:
    """Reproduce output-affecting inputs for a legacy refresh-only plan."""
    values = payload.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    outputs = values.get("outputs") if isinstance(values, dict) else None
    if not isinstance(root, dict) or not isinstance(outputs, dict):
        raise DriftContractError("Terraform state JSON has no platform values")

    addresses = _resource_addresses(root)

    def has_prefix(prefix: str) -> bool:
        return any(address.startswith(prefix) for address in addresses)

    governed_identity_prefixes = (
        "module.identity_change[0].",
        "module.identity_resilience[0].",
        "module.identity_finops[0].",
    )
    governed_identities = tuple(has_prefix(prefix) for prefix in governed_identity_prefixes)
    if any(governed_identities) and not all(governed_identities):
        raise DriftContractError("platform state has an incomplete governed identity set")

    plan_inputs: dict[str, Any] = {
        "enable_dev_operations_gateway": has_prefix(
            "azurerm_function_app_flex_consumption.dev_gateway[0]"
        ),
        "enable_governed_execution": all(governed_identities),
        "enable_llm": has_prefix("module.llm_azure_openai[0].azurerm_cognitive_account.primary"),
        "enable_ohl_scale_out_evidence_target": has_prefix(
            "azurerm_linux_virtual_machine_scale_set.ohl_evidence[0]"
        ),
        "enable_operational_history": has_prefix("module.operational_history_storage[0]."),
    }
    if not plan_inputs["enable_llm"]:
        return plan_inputs

    stored_digest = _stored_output_string(outputs, "resolved_models_sha256")
    capabilities = resolved_models.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise DriftContractError("resolved model capabilities are missing")
    if not all(isinstance(capability, dict) for capability in capabilities):
        raise DriftContractError("resolved model capabilities must contain objects")
    normalized = json.dumps(resolved_models, separators=(",", ":"), sort_keys=True)
    observed_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if observed_digest != stored_digest:
        raise DriftContractError("resolved model bindings do not match the stored platform output")
    active_capabilities = [
        capability for capability in capabilities if capability.get("status") != "hil-only"
    ]
    if not active_capabilities:
        raise DriftContractError("resolved model bindings contain no active capabilities")
    plan_inputs.update(
        {
            "resolved_capabilities": active_capabilities,
            "resolved_models_json": normalized,
            "resolved_models_sha256": stored_digest,
        }
    )
    return plan_inputs


def _stored_cost_pseudonym_key_secret_id(root: dict[str, Any]) -> str | None:
    """Return the platform-owned Operator pseudonym key binding when the platform created it."""
    try:
        resource = _resource_at_address(root, _COST_PSEUDONYM_KEY_ADDRESS)
    except LookupError:
        return None
    values = resource.get("values")
    secret_id = values.get("id") if isinstance(values, dict) else None
    if not isinstance(secret_id, str) or not secret_id or "\n" in secret_id:
        raise DriftContractError("platform state contains an invalid cost pseudonym key binding")
    return secret_id


def _stored_output_string(outputs: dict[str, Any], name: str) -> str:
    output = outputs.get(name)
    value = output.get("value") if isinstance(output, dict) else None
    if not isinstance(value, str) or not value or "\n" in value:
        raise DriftContractError(f"platform state is missing required {name} output")
    return value


def _resource_addresses(module: dict[str, Any]) -> frozenset[str]:
    resources = module.get("resources", [])
    children = module.get("child_modules", [])
    if not isinstance(resources, list) or not isinstance(children, list):
        raise DriftContractError("Terraform state contains an invalid module")
    addresses: set[str] = set()
    for resource in resources:
        address = resource.get("address") if isinstance(resource, dict) else None
        if not isinstance(address, str) or not address:
            raise DriftContractError("Terraform state contains an invalid resource")
        addresses.add(address)
    for child in children:
        if not isinstance(child, dict):
            raise DriftContractError("Terraform state contains an invalid child module")
        addresses.update(_resource_addresses(child))
    return frozenset(addresses)


def _resource_at_address(module: dict[str, Any], address: str) -> dict[str, Any]:
    resources = module.get("resources", [])
    if not isinstance(resources, list):
        raise DriftContractError("Terraform state module resources must be an array")
    matches = [
        resource
        for resource in resources
        if isinstance(resource, dict) and resource.get("address") == address
    ]
    children = module.get("child_modules", [])
    if not isinstance(children, list):
        raise DriftContractError("Terraform state child_modules must be an array")
    for child in children:
        if not isinstance(child, dict):
            raise DriftContractError("Terraform state contains an invalid child module")
        try:
            matches.append(_resource_at_address(child, address))
        except LookupError:
            pass
    if len(matches) > 1:
        raise DriftContractError("Terraform state contains duplicate service resources")
    if not matches:
        raise LookupError(address)
    return matches[0]


def _container_images(resource_values: dict[str, Any]) -> tuple[str, ...]:
    templates = resource_values.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise DriftContractError("service resource must contain one template")
    containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(containers, list):
        raise DriftContractError("service template containers must be an array")
    return tuple(
        image
        for container in containers
        if isinstance(container, dict)
        for image in (container.get("image"),)
        if isinstance(image, str)
    )


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DriftContractError(f"{path.name} must contain a JSON object")
    return payload


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")


def main() -> int:
    """Print drift coordinates or stored planning inputs for workflow use."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    roots = commands.add_parser("roots")
    roots.add_argument("--environment", required=True)
    image = commands.add_parser("stored-image")
    image.add_argument("--service", required=True)
    image.add_argument("--environment", required=True)
    image.add_argument("--repository", required=True)
    image.add_argument("--state-json", type=Path, required=True)
    bootstrap = commands.add_parser("bootstrap-inputs")
    bootstrap.add_argument("--state-json", type=Path, required=True)
    platform = commands.add_parser("platform-inputs")
    platform.add_argument("--state-json", type=Path, required=True)
    platform_output = commands.add_parser("platform-output-inputs")
    platform_output.add_argument("--state-json", type=Path, required=True)
    platform_output.add_argument("--resolved-models-json", type=Path, required=True)
    platform_output.add_argument("--output", type=Path, required=True)
    database = commands.add_parser("platform-database")
    database.add_argument("--state-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "roots":
            print(json.dumps([asdict(root) for root in production_roots(args.environment)]))
        elif args.command == "stored-image":
            print(
                stored_service_image(
                    _object(args.state_json),
                    contract=resolve_service(args.service, args.environment),
                    repository=args.repository,
                )
            )
        elif args.command == "bootstrap-inputs":
            print(json.dumps(stored_bootstrap_inputs(_object(args.state_json)), sort_keys=True))
        elif args.command == "platform-database":
            print(json.dumps(stored_platform_database(_object(args.state_json)), sort_keys=True))
        elif args.command == "platform-output-inputs":
            _write_private_json(
                args.output,
                stored_platform_output_inputs(
                    _object(args.state_json),
                    resolved_models=_object(args.resolved_models_json),
                ),
            )
        else:
            print(json.dumps(stored_platform_inputs(_object(args.state_json)), sort_keys=True))
    except (
        DriftContractError,
        LookupError,
        OSError,
        json.JSONDecodeError,
        ServiceContractError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
