#!/usr/bin/env python3
"""Resolve production Terraform roots and pre-refresh planning inputs."""

from __future__ import annotations

import argparse
import json
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
