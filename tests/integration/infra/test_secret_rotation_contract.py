from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dsn_rotation_uses_versionless_rbac_and_a_versioned_runtime_reference() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert "azurerm_key_vault_secret.state_store_dsn.id" in root
    resource = 'resource "azurerm_key_vault_secret" "state_store_dsn"'
    start = root.index(resource)
    block = root[start : root.index("\n}", start) + 2]
    assert "expiration_date" not in block

    assert "azurerm_key_vault_secret.state_store_dsn.resource_versionless_id" in root
    assert 'resource "azurerm_key_vault_secret" "operator_memory_dsn"' not in root
    assert 'resource "azurerm_key_vault_secret" "pattern_library_dsn"' not in root


def test_aks_dsn_requires_coordinated_rotation_without_independent_expiry() -> None:
    root = (ROOT / "infra/runtimes/aks/database/main.tf").read_text(encoding="utf-8")

    resource = 'resource "azurerm_key_vault_secret" "state_store_dsn"'
    start = root.index(resource)
    block = root[start : root.index("\n}", start) + 2]

    assert "expiration_date" not in block
    assert "checkov:skip=CKV_AZURE_41:Credential rotation requires coordinated" in block
    assert "azurerm_key_vault_secret.state_store_dsn.resource_versionless_id" in root
    assert "depends_on = [kubernetes_stateful_set_v1.postgres]" in block
    assert 'dsn                  = "postgresql://' in root
    assert "postgresql+psycopg://" not in root


def test_postgres_stateful_set_does_not_reuse_azure_tag_keys_as_labels() -> None:
    root = (ROOT / "infra/runtimes/aks/database/main.tf").read_text(encoding="utf-8")
    resource = 'resource "kubernetes_stateful_set_v1" "postgres"'
    start = root.index(resource)
    block = root[start : root.index("\n}", start) + 2]

    assert "labels = merge(var.tags" not in block
    assert '"app.kubernetes.io/name"       = "postgres"' in block
    assert '"fdai.io/runtime"              = "aks"' in block


def test_postgres_container_satisfies_restricted_pod_security() -> None:
    root = (ROOT / "infra/runtimes/aks/database/main.tf").read_text(encoding="utf-8")

    assert len(re.findall(r"run_as_non_root\s*=\s*true", root)) == 2
    assert len(re.findall(r"run_as_user\s*=\s*999", root)) == 2
    assert len(re.findall(r"run_as_group\s*=\s*999", root)) == 2
    assert "allow_privilege_escalation = false" in root
    assert 'drop = ["ALL"]' in root


def test_postgres_aks_publishes_role_scoped_ingestion_dsns() -> None:
    root = (ROOT / "infra/runtimes/aks/database/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/runtimes/aks/database/variables.tf").read_text(encoding="utf-8")

    assert 'name         = "fdai-ingestion-api-dsn"' in root
    assert 'name         = "fdai-ingestion-worker-dsn"' in root
    assert "&options=-c%20role%3Dfdai_ingestion_api" in root
    assert "&options=-c%20role%3Dfdai_ingestion_worker" in root
    assert "azurerm_key_vault_secret.ingestion_api_dsn.resource_versionless_id" in root
    assert "azurerm_key_vault_secret.ingestion_worker_dsn.resource_versionless_id" in root
    assert 'resource "azurerm_role_assignment" "ingestion_api_secret_reader"' in root
    assert "principal_id         = var.ingestion_api_principal_id" in root
    assert 'resource "azurerm_role_assignment" "ingestion_worker_secret_reader"' in root
    assert "principal_id         = var.ingestion_worker_principal_id" in root
    assert 'variable "ingestion_api_principal_id"' in variables
    assert 'variable "ingestion_worker_principal_id"' in variables
    assert "count = var.ingestion_api_principal_id == null ? 0 : 1" in root
    assert "count = var.ingestion_worker_principal_id == null ? 0 : 1" in root
    assert "to   = azurerm_role_assignment.ingestion_api_secret_reader[0]" in root
    assert "to   = azurerm_role_assignment.ingestion_worker_secret_reader[0]" in root
