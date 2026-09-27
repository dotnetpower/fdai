from __future__ import annotations

from fdai_deployment_cli.aks_catalog_review import REQUIRED_GITHUB_APP_PERMISSIONS
from fdai_deployment_cli.aks_workload_jobs import prepare_aks_scheduled_jobs

_REVISION = "a" * 40
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_TENANT = "00000000-0000-0000-0000-000000000001"
_IMAGE = "example.azurecr.io/fdai@sha256:" + "b" * 64
_CLUSTER_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/example/providers/"
    "Microsoft.ContainerService/managedClusters/runtime"
)


def _identity(name: str, suffix: int) -> dict[str, str]:
    return {
        "resource_id": (
            f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/example/providers/"
            f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
        ),
        "client_id": f"00000000-0000-0000-0000-{suffix:012d}",
    }


def _prepare(*, catalog_binding: object = None, selected: bool = False):
    return prepare_aks_scheduled_jobs(
        refs={"core-control-plane": _IMAGE},
        core_identity=_identity("core", 2),
        inventory_identity=_identity("inventory", 3),
        canary_identity=_identity("canary", 4),
        core_environment={
            "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "KAFKA_TOPIC_EVENTS": "events",
        },
        substrate_outputs={
            "operational_kafka": "example.servicebus.windows.net:9093",
            "workspace": "/subscriptions/example/resourceGroups/example/providers/workspaces/main",
            "catalog_review_gitops_binding": catalog_binding,
            "operational_history_container_url": "https://example.invalid/history",
        },
        source_revision=_REVISION,
        tenant_id=_TENANT,
        subscription_id=_SUBSCRIPTION,
        catalog_review_selected=selected,
        cluster_id=_CLUSTER_ID,
        namespace="fdai-runtime",
    )


def test_prepares_inventory_jobs_and_protected_bindings() -> None:
    prepared = _prepare()

    assert set(prepared.jobs) == {
        "analyzer",
        "canary",
        "inventory",
        "observation-campaign",
        "operational-history-lifecycle",
    }
    inventory = prepared.jobs["inventory"]
    assert inventory["environment"]["FDAI_INVENTORY_SCOPES"] == _SUBSCRIPTION  # type: ignore[index]
    assert inventory["environment"]["FDAI_INVENTORY_SOURCES"] == "arg,arm"  # type: ignore[index]
    assert set(prepared.protected_template_digests) == set(prepared.jobs)
    assert all(len(digest) == 64 for digest in prepared.protected_template_digests.values())
    assert set(prepared.protected_identity_bindings) == set(prepared.jobs)
    assert (
        prepared.protected_identity_bindings["inventory"]["identity_resource_id"]
        == _identity("inventory", 3)["resource_id"].casefold()
    )
    assert prepared.catalog_review_available is False


def test_prepares_selected_catalog_job_without_receipt_authority() -> None:
    binding = {
        "enabled": True,
        "owner": "example",
        "repo": "deployment-config",
        "auth_mode": "github_app",
        "default_branch": "main",
        "permissions": REQUIRED_GITHUB_APP_PERMISSIONS,
        "app_client_id": "client",
        "app_installation_id": "1",
        "app_private_key_secret_id": (
            f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/example/providers/"
            "Microsoft.KeyVault/vaults/example/secrets/catalog-review-key"
        ),
    }

    prepared = _prepare(catalog_binding=binding, selected=True)

    catalog_job = prepared.jobs["catalog-review"]
    assert catalog_job["suspend"] is True
    assert catalog_job["environment"]["FDAI_GITOPS_DEFAULT_BRANCH"] == "main"  # type: ignore[index]
    assert catalog_job["secret_environment"] == {
        "FDAI_GITHUB_APP_PRIVATE_KEY": "catalog-review-key",
        "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
    }
    assert prepared.catalog_review_available is True
