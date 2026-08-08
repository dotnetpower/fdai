"""Static contract tests for the optional APIM AI gateway module."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = REPO_ROOT / "infra" / "modules" / "llm" / "apim-ai-gateway"


def _policy() -> tuple[ElementTree.Element, str]:
    text = (MODULE / "policy.xml.tftpl").read_text(encoding="utf-8")
    replacements = {
        "${tenant_id}": "00000000-0000-0000-0000-000000000000",
        "${frontend_audience}": "api://fdai-model-gateway",
        "${ptu_backend_id}": "primary-ptu",
        "${standard_backend_id}": "primary-standard",
        "${api_version}": "2024-10-21",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return ElementTree.fromstring(text), text  # noqa: S314 - repo-owned static policy


def test_policy_authenticates_caller_and_backend_with_entra() -> None:
    root, _text = _policy()

    validate = root.find("./inbound/validate-jwt")
    backend_auth = root.find("./inbound/authentication-managed-identity")

    assert validate is not None
    assert validate.findtext("./audiences/audience") == "api://fdai-model-gateway"
    assert backend_auth is not None
    assert backend_auth.attrib["resource"] == "https://cognitiveservices.azure.com"


def test_policy_retries_once_from_ptu_to_standard_only_on_429() -> None:
    root, text = _policy()
    retry = root.find("./backend/retry")

    assert retry is not None
    assert retry.attrib["count"] == "1"
    assert "StatusCode == 429" in retry.attrib["condition"]
    assert 'backend-id="primary-ptu"' in text
    assert 'backend-id="primary-standard"' in text
    assert 'value="true"' in text


def test_policy_emits_every_required_route_evidence_header() -> None:
    root, _text = _policy()
    names = {node.attrib["name"] for node in root.findall("./outbound/set-header")}

    assert names == {
        "x-fdai-model-backend",
        "x-fdai-capacity-unit",
        "x-fdai-spillover",
    }


def test_module_does_not_create_an_apim_service() -> None:
    main = (MODULE / "main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_api_management" ' not in main
    assert 'resource "azurerm_api_management_backend"' in main
    assert 'resource "azurerm_api_management_api_policy"' in main


def test_root_integration_is_opt_in_and_disabled_by_default() -> None:
    variables = (REPO_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    main = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'variable "enable_model_apim_gateway"' in variables
    assert "default     = false" in variables
    assert "count  = var.enable_model_apim_gateway ? 1 : 0" in main
