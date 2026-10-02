"""Read back AKS node pools before runtime effects."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fdai_deployment_cli import standalone_planned_outputs
from fdai_deployment_cli.standalone_checkpoint_failure import (
    ManagedHostCheckpointError,
    sanitize_failure_text,
)
from fdai_deployment_cli.standalone_host_state import private_json


def guard_existing_runtime_node_pools(context: dict[str, object], work_dir: Path) -> None:
    if _runtime_platform(context) != "aks":
        return
    application_values = private_json(
        work_dir / "application.auto.tfvars.json", "application variables"
    )
    cluster_name = (
        f"aks-{application_values['workload']}-{application_values['env']}-"
        f"{application_values['region_short']}"
    )
    resource_group = str(
        context.get("resource_group_name") or application_values.get("resource_group_name")
    )
    if not resource_group or "None" in resource_group:
        resource_group = str(
            standalone_planned_outputs.read_output(
                Path(str(context["infra"])),
                "resource_group_name",
                raw=True,
                reason="runtime resource group readback failed",
            )
        )
    pools = _aks_node_pools(
        context=context,
        work_dir=work_dir,
        resource_group=resource_group,
        cluster_name=cluster_name,
    )
    if "runtime" not in pools:
        return
    if _runtime_node_pool_in_state(Path(str(context["runtime_infra"]))):
        return
    raise ManagedHostCheckpointError(
        "aks_node_pool_exists_outside_state",
        (
            "AKS node pool runtime already exists outside Terraform state. "
            "Removing it needs explicit Owner confirmation before any apply."
        ),
        excerpt=(
            "AKS node pool runtime already exists outside Terraform state. "
            "Removing it needs explicit Owner confirmation before any apply."
        ),
    )


def _aks_node_pools(
    *,
    context: dict[str, object],
    work_dir: Path,
    resource_group: str,
    cluster_name: str,
) -> set[str]:
    completed = subprocess.run(
        (
            "az",
            "aks",
            "nodepool",
            "list",
            "--subscription",
            str(context["subscription_id"]),
            "--resource-group",
            resource_group,
            "--cluster-name",
            cluster_name,
            "--query",
            "[].name",
            "--output",
            "json",
            "--only-show-errors",
        ),
        cwd=work_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        message = f"{completed.stdout}\n{completed.stderr}"
        if re.search(r"(?i)(not\s+found|resourcenotfound|could not be found)", message):
            return set()
        raise ManagedHostCheckpointError(
            "aks_node_pool_readback_failed",
            "AKS node pool readback failed",
            excerpt=sanitize_failure_text(message),
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ManagedHostCheckpointError(
            "aks_node_pool_readback_failed",
            "AKS node pool readback returned invalid JSON",
            excerpt="AKS node pool readback returned invalid JSON",
        ) from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManagedHostCheckpointError(
            "aks_node_pool_readback_failed",
            "AKS node pool readback returned an invalid shape",
            excerpt="AKS node pool readback returned an invalid shape",
        )
    return set(value)


def _runtime_node_pool_in_state(runtime_infra: Path) -> bool:
    completed = subprocess.run(
        ("terraform", "state", "list"),
        cwd=runtime_infra,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        return False
    return "azurerm_kubernetes_cluster_node_pool.user" in set(completed.stdout.split())


def _runtime_platform(context: dict[str, object]) -> str:
    value = context.get("runtime_profile")
    if value is None:
        return "container-apps"
    platform = value.get("runtime_platform") if isinstance(value, dict) else None
    if platform not in {"container-apps", "aks"}:
        raise ValueError("runtime deployment platform is invalid")
    return str(platform)
