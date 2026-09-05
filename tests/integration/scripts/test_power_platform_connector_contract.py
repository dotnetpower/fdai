"""Power Platform custom connector contract checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "config" / "power-platform" / "fdai-sharepoint-connector.openapi.yaml"
ROOT_TERRAFORM = REPO_ROOT / "infra" / "main.tf"
ROOT_VARIABLES = REPO_ROOT / "infra" / "variables.tf"
CONTAINER_APP = REPO_ROOT / "infra" / "modules" / "ingestion-gateway" / "container-app"


def test_connector_uses_cross_tenant_oauth_and_sequenced_binary_intake() -> None:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    oauth = payload["securityDefinitions"]["oauth2"]
    assert oauth["flow"] == "accessCode"
    assert "/common/oauth2/v2.0/authorize" in oauth["authorizationUrl"]
    assert "/common/oauth2/v2.0/token" in oauth["tokenUrl"]
    assert "DocumentConnector.Ingest" in next(iter(oauth["scopes"]))

    paths = payload["paths"]
    content = next(value["put"] for key, value in paths.items() if key.endswith("/content"))
    deleted = next(value["post"] for key, value in paths.items() if key.endswith("/deleted"))
    content_refs = {item["$ref"] for item in content["parameters"] if "$ref" in item}
    deleted_refs = {item["$ref"] for item in deleted["parameters"] if "$ref" in item}
    assert "#/parameters/eventSequence" in content_refs
    assert "#/parameters/eventSequence" in deleted_refs
    assert payload["parameters"]["connectorId"]["default"] == "<fdai-connector-id>"
    body = next(item for item in content["parameters"] if item.get("in") == "body")
    assert body["schema"] == {"type": "string", "format": "binary"}


def test_connector_definition_contains_only_generic_placeholders() -> None:
    source = CONTRACT.read_text(encoding="utf-8")

    assert "fdai-ingestion.example.com" in source
    assert "<fdai-connector-app-id>" in source
    assert "tenant_id" not in source


def test_connector_deployment_wires_only_explicit_policy_values() -> None:
    root = ROOT_TERRAFORM.read_text(encoding="utf-8")
    variables = ROOT_VARIABLES.read_text(encoding="utf-8")
    module = (CONTAINER_APP / "main.tf").read_text(encoding="utf-8")
    module_variables = (CONTAINER_APP / "variables.tf").read_text(encoding="utf-8")
    names = (
        "power_platform_connector_enabled",
        "power_platform_connector_id",
        "power_platform_source_tenant_id",
        "power_platform_allowed_client_ids",
        "power_platform_api_audience",
        "power_platform_collection_id",
        "power_platform_access_descriptor_ref",
        "power_platform_reader_groups",
        "power_platform_retention_policy_version",
        "power_platform_purposes",
    )

    for name in names:
        assert f'variable "{name}"' in variables
        assert re.search(rf"{name}\s*=\s*var\.{name}", root)
        assert f'variable "{name}"' in module_variables
    assert "FDAI_CONNECTOR_ALLOWED_TENANT_IDS" in module
    assert "FDAI_CONNECTOR_ALLOWED_CLIENT_IDS" in module
    assert "FDAI_CONNECTOR_API_AUDIENCE" in module
    assert "Power Platform connector activation requires complete" in module
