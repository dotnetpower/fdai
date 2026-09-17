"""AKS runtime topology inventory deployment identity contract."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JOB = _ROOT / "infra/modules/compute/container-apps/inventory_job.tf"
_MAIN = _ROOT / "infra/main.tf"
_AKS_WORKLOADS = _ROOT / "infra/runtimes/aks/workloads/main.tf"


def test_inventory_job_uses_short_lived_workload_identity_without_token_secret() -> None:
    job = _JOB.read_text(encoding="utf-8")

    assert 'name  = "FDAI_KUBERNETES_AUTH_MODE"' in job
    assert 'value = "workload-identity"' in job
    assert 'name  = "FDAI_KUBERNETES_CA_PEM"' in job
    assert 'name  = "FDAI_KUBERNETES_AUDIENCE"' in job
    assert "FDAI_KUBERNETES_TOKEN" not in job
    assert "service-account" not in job
    assert "must be configured together" in job


def test_inventory_identity_gets_only_aks_rbac_reader_for_configured_cluster() -> None:
    main = _MAIN.read_text(encoding="utf-8")
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_role_assignment" "inventory_kubernetes_reader"' in main
    assert 'role_definition_name = "Azure Kubernetes Service RBAC Reader"' in main
    assert "principal_id         = module.inventory_identity.principal_id" in main
    assert 'role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"' not in main
    assert "for_each             = nonsensitive(local.inventory_kubernetes_cluster_refs)" in main
    assert "scope                = each.value" in main
    assert (
        variables.count(
            "^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
            "microsoft\\\\.containerservice/managedclusters/[^/]+$"
        )
        == 2
    )


def test_inventory_job_accepts_fleet_json_without_bearer_tokens() -> None:
    main = _MAIN.read_text(encoding="utf-8")
    job = _JOB.read_text(encoding="utf-8")
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")

    assert 'variable "inventory_kubernetes_cluster_bindings_json"' in variables
    assert '"FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON"' in job
    assert "fleet JSON and legacy bindings are mutually exclusive" in job
    assert "inventory_kubernetes_cluster_bindings_json" in main
    assert "KUBERNETES_TOKEN" not in job


def test_aks_inventory_job_gets_only_reviewed_in_cluster_read_permissions() -> None:
    workloads = _AKS_WORKLOADS.read_text(encoding="utf-8")
    role = workloads.split('resource "kubernetes_cluster_role_v1" "inventory_reader"', maxsplit=1)[
        1
    ].split('resource "kubernetes_cluster_role_binding_v1" "inventory_reader"', maxsplit=1)[0]

    assert 'resource "kubernetes_cluster_role_v1" "inventory_reader"' in workloads
    assert 'resource "kubernetes_cluster_role_binding_v1" "inventory_reader"' in workloads
    assert 'name      = kubernetes_service_account_v1.identity["job-inventory"]' in workloads
    assert 'verbs      = ["get", "list", "watch"]' in workloads
    assert '"pods"' in role
    assert '"nodes"' in role
    assert '"events"' in role
    assert '"endpointslices"' in role
    assert '"secrets"' not in role
    assert '"configmaps"' not in role
    assert '"create"' not in role
    assert '"update"' not in role
    assert '"patch"' not in role
    assert '"delete"' not in role


def test_aks_isolated_executor_gets_only_registered_namespace_effect_permissions() -> None:
    workloads = _AKS_WORKLOADS.read_text(encoding="utf-8")
    role = workloads.split(
        'resource "kubernetes_role_v1" "executor_kubernetes_effect"', maxsplit=1
    )[1].split('resource "kubernetes_role_binding_v1" "executor_kubernetes_effect"', maxsplit=1)[0]

    assert '"pods"' in role
    assert 'verbs      = ["get", "delete"]' in role
    assert '"deployments"' in role
    assert 'verbs      = ["get", "patch"]' in role
    assert '"deployments/scale"' in role
    assert 'verbs      = ["get", "update"]' in role
    assert '"secrets"' not in role
    assert '"configmaps"' not in role
    assert '"create"' not in role
    assert '"list"' not in role
    assert '"watch"' not in role
    assert (
        'name      = kubernetes_service_account_v1.identity["workload-isolated-executor"]'
        in workloads
    )
    assert 'kind      = "Role"' in workloads


def test_external_scale_grant_is_named_and_bound_only_to_thor_runtime() -> None:
    workloads = _AKS_WORKLOADS.read_text(encoding="utf-8")
    role = workloads.split('resource "kubernetes_role_v1" "executor_external_scale"', 1)[1].split(
        'resource "kubernetes_role_binding_v1" "executor_external_scale"', 1
    )[0]
    binding = workloads.split('resource "kubernetes_role_binding_v1" "executor_external_scale"', 1)[
        1
    ].split('resource "azurerm_federated_identity_credential"', 1)[0]

    assert 'resources      = ["deployments"]' in role
    assert 'resources      = ["deployments/scale"]' in role
    assert role.count("resource_names = sort(tolist(each.value))") == 2
    assert 'verbs          = ["get"]' in role
    assert 'verbs          = ["get", "update"]' in role
    assert "namespace = each.key" in role
    assert "local.executor_kubernetes_effect_enabled" in role
    assert 'environment["FDAI_EXECUTION_VENUE"] == "deployed"' in role
    assert 'environment["FDAI_KUBERNETES_DIRECT_API_JSON"]).allowed_namespaces' in role
    for forbidden in (
        '"*"',
        '"pods"',
        '"secrets"',
        '"patch"',
        '"delete"',
        '"create"',
        '"list"',
        '"watch"',
    ):
        assert forbidden not in role
    assert 'kind      = "Role"' in binding
    assert 'identity["workload-isolated-executor"]' in binding
    assert binding.count("subject {") == 1
    assert "namespace = kubernetes_namespace_v1.runtime.metadata[0].name" in binding


def test_external_scale_targets_default_to_empty_and_reject_broad_scope() -> None:
    variables = (_AKS_WORKLOADS.parent / "variables.tf").read_text(encoding="utf-8")
    target_input = variables.split('variable "executor_external_scale_targets"', 1)[1].split(
        'variable "tenant_id"', 1
    )[0]

    assert "type        = map(set(string))" in target_input
    assert "default     = {}" in target_input
    assert "nullable    = false" in target_input
    assert "length(var.executor_external_scale_targets) <= 16" in target_input
    assert "length(names) >= 1 && length(names) <= 16" in target_input
    assert "namespace != var.namespace" in target_input
    assert 'namespace != "default"' in target_input
    assert '!startswith(namespace, "kube-")' in target_input
