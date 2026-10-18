"""Infrastructure contract for production decision-evidence admission."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE = _ROOT / "infra/services/core-control-plane"
_ROOT_VARIABLES = (_SERVICE / "variables.tf").read_text(encoding="utf-8")
_ROOT_MAIN = (_SERVICE / "main.tf").read_text(encoding="utf-8")
_MODULE_VARIABLES = (_SERVICE / "modules/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)
_MODULE_MAIN = (_SERVICE / "modules/core-control-plane/main.tf").read_text(encoding="utf-8")
_SERVICE_DEPLOY = (_ROOT / ".github/workflows/service-deploy.yml").read_text(encoding="utf-8")
_PLATFORM_MAIN = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
_PLATFORM_OUTPUTS = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
_STORAGE_MODULE = (_ROOT / "infra/modules/storage/case-history/main.tf").read_text(encoding="utf-8")


def test_core_service_exposes_optional_private_container_binding() -> None:
    assert 'variable "decision_evidence_container_url"' in _ROOT_VARIABLES
    assert "must be empty or one HTTPS Blob container URL" in _ROOT_VARIABLES
    assert re.search(
        r"(?m)^\s*decision_evidence_container_url\s*=\s*"
        r"var[.]decision_evidence_container_url\s*$",
        _ROOT_MAIN,
    )
    assert 'variable "decision_evidence_container_url"' in _MODULE_VARIABLES
    assert '"FDAI_DECISION_EVIDENCE_CONTAINER_URL"' in _MODULE_MAIN


def test_service_deploy_uses_authoritative_platform_output() -> None:
    assert 'terraform -chdir="$TRUSTED_CONTROLS/infra"' in _SERVICE_DEPLOY
    assert "output -raw decision_evidence_container_url" in _SERVICE_DEPLOY
    assert 'DECISION_EVIDENCE_CONTAINER_URL="$decision_evidence_container_url"' in (_SERVICE_DEPLOY)


def test_platform_uses_dedicated_immutable_read_only_storage() -> None:
    assert 'module "decision_evidence_storage"' in _PLATFORM_MAIN
    assert 'container_name                = "decision-evidence"' in _PLATFORM_MAIN
    assert 'runtime_role_definition_name  = "Storage Blob Data Reader"' in _PLATFORM_MAIN
    assert "immutability_period_days      = 90" in _PLATFORM_MAIN
    assert 'resource "azurerm_private_endpoint" "decision_evidence_blob"' in _PLATFORM_MAIN
    assert 'output "decision_evidence_container_url"' in _PLATFORM_OUTPUTS
    assert "azurerm_storage_container_immutability_policy" in _STORAGE_MODULE
    assert "role_definition_name = var.runtime_role_definition_name" in _STORAGE_MODULE
