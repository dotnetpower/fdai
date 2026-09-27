"""Render focused AKS scheduled-job values for standalone deployment."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.aks_catalog_review import aks_catalog_review_configuration
from fdai_deployment_cli.aks_job_execution import protected_cronjob_template_digest
from fdai_deployment_cli.standalone_aks_job_execution import (
    protected_service_account_binding,
)

_AKS_RESOURCE_ID = re.compile(
    r"/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.containerservice/managedclusters/[^/]+",
    re.IGNORECASE,
)
_SERVICE_ACCOUNT_ROOT = "/var/run/secrets/kubernetes.io/serviceaccount"


@dataclass(frozen=True, slots=True)
class AksScheduledJobPreparation:
    """Terraform job values plus independently retained execution bindings."""

    jobs: dict[str, dict[str, object]]
    protected_template_digests: dict[str, str]
    protected_identity_bindings: dict[str, dict[str, object]]
    catalog_review_available: bool


def build_aks_scheduled_job(
    refs: dict[str, Any],
    identity: dict[str, Any],
    command: list[str],
    schedule: str,
    environment: Mapping[str, object],
    secret_environment: Mapping[str, str],
    *,
    component: str,
    deadline_seconds: int,
    retry_limit: int = 1,
    suspend: bool = False,
) -> dict[str, object]:
    """Build one runtime-neutral scheduled or suspended AKS job value."""

    image = refs.get("core-control-plane")
    if not isinstance(image, str):
        raise TypeError("AKS scheduled job image is unavailable")
    return {
        "component": component,
        "image": image,
        "identity_resource_id": identity["resource_id"],
        "identity_client_id": identity["client_id"],
        "command": command,
        "args": [],
        "schedule": schedule,
        "suspend": suspend,
        "deadline_seconds": deadline_seconds,
        "retry_limit": retry_limit,
        "cpu": "500m",
        "memory": "1Gi",
        "environment": {name: str(value) for name, value in environment.items()},
        "secret_environment": secret_environment,
    }


def prepare_aks_scheduled_jobs(
    *,
    refs: dict[str, Any],
    core_identity: dict[str, Any],
    inventory_identity: dict[str, Any],
    canary_identity: dict[str, Any],
    core_environment: Mapping[str, object],
    substrate_outputs: Mapping[str, object],
    source_revision: str,
    tenant_id: str,
    subscription_id: str,
    catalog_review_selected: bool,
    cluster_id: str,
    namespace: str,
) -> AksScheduledJobPreparation:
    """Build scheduled Jobs and seal their template and workload-identity contracts."""

    inventory_environment = {
        **core_environment,
        "AZURE_CLIENT_ID": inventory_identity["client_id"],
        "FDAI_MI_CLIENT_ID": inventory_identity["client_id"],
    }
    jobs = {
        "analyzer": build_aks_scheduled_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.analyzer_tick_cli"],
            "* * * * *",
            {
                **inventory_environment,
                "FDAI_ANALYZER_SCHEDULING_MODE": "kubernetes_cronjob",
                "FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS": "900",
            },
            {
                "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                "FDAI_INVENTORY_DSN": "fdai-state-store-dsn",
            },
            component="analysis",
            deadline_seconds=240,
        ),
        "canary": build_aks_scheduled_job(
            refs,
            canary_identity,
            ["python", "-m", "fdai.delivery.canary_cli"],
            "*/5 * * * *",
            {
                "AZURE_CLIENT_ID": canary_identity["client_id"],
                "KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["operational_kafka"],
                "FDAI_CANARY_TOPIC": "fdai.control.canary",
                "FDAI_MI_CLIENT_ID": canary_identity["client_id"],
            },
            {},
            component="canary",
            deadline_seconds=120,
            retry_limit=2,
        ),
        "inventory": build_aks_scheduled_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.inventory_sync_cli"],
            "* * * * *",
            {
                **inventory_environment,
                **aks_inventory_binding_environment(cluster_id),
                "FDAI_INVENTORY_SCOPES": subscription_id,
                "FDAI_INVENTORY_SOURCES": "arg,arm",
                "FDAI_MONITOR_WORKSPACE_ID": substrate_outputs["workspace"],
            },
            {"FDAI_INVENTORY_DSN": "fdai-state-store-dsn"},
            component="inventory",
            deadline_seconds=900,
        ),
        "observation-campaign": build_aks_scheduled_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.observation_campaign_cli"],
            "* * * * *",
            {
                **inventory_environment,
                "FDAI_OBSERVATION_SCOPES": subscription_id,
            },
            {"FDAI_OBSERVATION_DSN": "fdai-state-store-dsn"},
            component="observation",
            deadline_seconds=900,
        ),
    }
    catalog_review = aks_catalog_review_configuration(
        substrate_outputs["catalog_review_gitops_binding"],
        selected=catalog_review_selected,
        source_revision=source_revision,
    )
    if catalog_review is not None:
        jobs["catalog-review"] = build_aks_scheduled_job(
            refs,
            core_identity,
            ["python", "-m", "fdai.runtime.operational_catalog_review_trigger"],
            "0 0 1 1 *",
            {**core_environment, **catalog_review.environment},
            {
                **catalog_review.secret_environment,
                "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
            },
            component="catalog-review",
            deadline_seconds=300,
            retry_limit=0,
            suspend=True,
        )
    operational_history_container_url = str(substrate_outputs["operational_history_container_url"])
    if operational_history_container_url:
        jobs["operational-history-lifecycle"] = build_aks_scheduled_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
            "0 * * * *",
            {
                **inventory_environment,
                "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": operational_history_container_url,
                "FDAI_OPERATIONAL_HISTORY_MODE": "shadow",
                "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS": "32",
            },
            {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
            component="operational-history",
            deadline_seconds=1800,
            retry_limit=0,
        )
    template_digests = {
        name: protected_cronjob_template_digest(
            job,
            template_name=name,
            namespace=namespace,
            source_revision=source_revision,
        )
        for name, job in jobs.items()
    }
    identity_bindings = {
        name: protected_service_account_binding(
            job,
            template_name=name,
            namespace=namespace,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
        )
        for name, job in jobs.items()
    }
    return AksScheduledJobPreparation(
        jobs=jobs,
        protected_template_digests=template_digests,
        protected_identity_bindings=identity_bindings,
        catalog_review_available=catalog_review is not None,
    )


def aks_inventory_binding_environment(cluster_id: str) -> dict[str, str]:
    """Bind inventory to its in-cluster read-only ServiceAccount projection."""

    normalized_cluster_id = cluster_id.strip()
    if _AKS_RESOURCE_ID.fullmatch(normalized_cluster_id) is None:
        raise ValueError("AKS runtime cluster id is invalid")
    return {
        "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.default.svc",
        "FDAI_KUBERNETES_CLUSTER_REF": normalized_cluster_id,
        "FDAI_KUBERNETES_AUTH_MODE": "service-account",
        "FDAI_KUBERNETES_CA_PATH": f"{_SERVICE_ACCOUNT_ROOT}/ca.crt",
        "FDAI_KUBERNETES_TOKEN_PATH": f"{_SERVICE_ACCOUNT_ROOT}/token",
    }


def aks_kubernetes_direct_api_environment(
    cluster_id: str,
    *,
    namespace: str,
) -> dict[str, str]:
    """Bind namespace-limited Kubernetes effects to the isolated Executor."""

    normalized_cluster_id = cluster_id.strip()
    if _AKS_RESOURCE_ID.fullmatch(normalized_cluster_id) is None:
        raise ValueError("AKS runtime cluster id is invalid")
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise ValueError("AKS runtime namespace is invalid")
    return {
        "FDAI_KUBERNETES_DIRECT_API_JSON": json.dumps(
            {
                "allowed_namespaces": [namespace],
                "api_server": "https://kubernetes.default.svc",
                "ca_path": f"{_SERVICE_ACCOUNT_ROOT}/ca.crt",
                "cluster_ref": normalized_cluster_id,
                "token_path": f"{_SERVICE_ACCOUNT_ROOT}/token",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    }


__all__ = [
    "AksScheduledJobPreparation",
    "aks_inventory_binding_environment",
    "aks_kubernetes_direct_api_environment",
    "build_aks_scheduled_job",
    "prepare_aks_scheduled_jobs",
]
