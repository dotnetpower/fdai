"""Signal-probe builders for catalog-backed chaos scenarios."""

from __future__ import annotations

from typing import Any

from fdai.core.chaos.injector import SignalProbe
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.delivery.chaos.aoai_ratelimit import AoaiRateLimitProbe
from fdai.delivery.chaos.azure_ops import AzCliStateProbe
from fdai.delivery.chaos.chaos_mesh import ChaosMeshInjectedProbe
from fdai.delivery.chaos.factory_bodies import _crd_name, _litmus_engine_name
from fdai.delivery.chaos.litmus import LitmusChaosResultProbe
from fdai.delivery.chaos.live_injectors import (
    AzureMonitorCpuProbe,
    AzVmMemProbe,
    KubeBackendHealthProbe,
    KubeEventPodRestartProbe,
    KubeRolloutStallProbe,
)
from fdai.delivery.chaos.mysql_load import AzureMonitorDbCpuProbe


def _build_chaos_mesh_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    injector_ref = str(entry.spec["injector"])
    kind = injector_ref.split(":", 1)[1] if ":" in injector_ref else "PodChaos"
    return ChaosMeshInjectedProbe(
        context=str(ctx["kubectl_context"]),
        kind=kind,
        name=_crd_name(entry),
        namespace=str(ctx["chaos_namespace"]),
    )


def _build_litmus_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return LitmusChaosResultProbe(
        context=str(ctx["kubectl_context"]),
        engine_name=_litmus_engine_name(entry),
        experiment_name=str(entry.spec["provenance"]["source_ref"]),
        namespace=str(ctx["litmus_namespace"]),
    )


def _build_pod_restart_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return KubeEventPodRestartProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
    )


def _build_backend_health_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return KubeBackendHealthProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        service=str(ctx.get("backend_service", "api-backend")),
    )


def _build_rollout_stall_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    if str(entry.spec.get("injector", "")).startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    return KubeRolloutStallProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        selector=f"app={ctx.get('workload_label', 'api-backend')}",
    )


def _build_host_cpu_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return AzureMonitorCpuProbe(
        vm_resource_id=str(ctx["vm_resource_id"]),
        threshold_pct=float(ctx.get("vm_cpu_threshold_pct", 40.0)),
    )


def _build_host_memory_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return AzVmMemProbe(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        min_available_mb=int(ctx.get("vm_mem_min_available_mb", 350)),
    )


def _build_db_cpu_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return AzureMonitorDbCpuProbe(
        server_resource_id=str(ctx["mysql_server_resource_id"]),
        threshold_pct=float(ctx.get("mysql_cpu_threshold_pct", 25.0)),
    )


def _build_rate_limit_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return AoaiRateLimitProbe(
        request_fn=ctx["aoai_probe_request_fn"],
        samples=int(ctx.get("aoai_probe_samples", 5)),
    )


def _build_cm_status_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    return _build_chaos_mesh_probe(entry, ctx)


def _vm_run_command_probe(ctx: dict[str, Any], script: str, expected: str) -> AzCliStateProbe:
    return AzCliStateProbe(
        command=(
            "az",
            "vm",
            "run-command",
            "invoke",
            "-g",
            str(ctx["resource_group"]),
            "-n",
            str(ctx["vm_name"]),
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            "--query",
            "value[0].message",
            "-o",
            "tsv",
        ),
        expected_substrings=(expected,),
    )


def _build_azure_state_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec["injector"])
    params = entry.spec.get("params") or {}
    resource_group = str(ctx["resource_group"])
    if ref == "az:vm-network-latency":
        interface = str(ctx.get("vm_interface", "eth0"))
        return _vm_run_command_probe(ctx, f"tc qdisc show dev {interface}", "delay")
    if ref == "az:vm-packet-loss":
        interface = str(ctx.get("vm_interface", "eth0"))
        return _vm_run_command_probe(ctx, f"tc qdisc show dev {interface}", "loss")
    if ref == "az:vm-network-disconnect":
        destination = str(
            params.get("destination", ctx.get("network_disconnect_destination", "10.0.0.0/8"))
        )
        return _vm_run_command_probe(
            ctx,
            f"iptables -C OUTPUT -d {destination} -j DROP && echo blocked",
            "blocked",
        )
    if ref == "az:vm-stop-service":
        service = str(params.get("service", ctx.get("stop_service_name", "myservice")))
        return _vm_run_command_probe(
            ctx,
            f"systemctl is-active {service} 2>/dev/null || true",
            "inactive",
        )
    if ref == "az:vm-lifecycle":
        action = str(params.get("action", "deallocate"))
        if action == "deallocate":
            return AzCliStateProbe(
                command=(
                    "az",
                    "vm",
                    "get-instance-view",
                    "-g",
                    resource_group,
                    "-n",
                    str(ctx["vm_name"]),
                    "--query",
                    "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]",
                    "-o",
                    "tsv",
                ),
                expected_substrings=("PowerState/deallocated",),
            )
        return AzCliStateProbe(
            command=(
                "az",
                "vm",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["vm_name"]),
                "--query",
                "provisioningState",
                "-o",
                "tsv",
            ),
            expected_substrings=("Succeeded",),
        )
    if ref == "az:vmss-lifecycle":
        return AzCliStateProbe(
            command=(
                "az",
                "vmss",
                "list-instances",
                "-g",
                resource_group,
                "-n",
                str(ctx["vmss_name"]),
                "--expand",
                "instanceView",
                "--query",
                "[].instanceView.statuses[?starts_with(code, 'PowerState/')].code",
                "-o",
                "tsv",
            ),
            expected_substrings=("PowerState/deallocated",),
        )
    if ref == "az:cosmosdb-failover":
        priority_zero = next(
            (
                item.split("=", 1)[0]
                for item in str(params["failover_priorities"]).split()
                if item.endswith("=0")
            ),
            "",
        )
        return AzCliStateProbe(
            command=(
                "az",
                "cosmosdb",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["cosmos_account_name"]),
                "--query",
                "writeLocations[?failoverPriority==`0`].locationName | [0]",
                "-o",
                "tsv",
            ),
            expected_substrings=(priority_zero,),
        )
    if ref == "az:keyvault-deny":
        return AzCliStateProbe(
            command=(
                "az",
                "keyvault",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["keyvault_name"]),
                "--query",
                "properties.networkAcls.defaultAction",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    if ref == "az:nsg-rule":
        return AzCliStateProbe(
            command=(
                "az",
                "network",
                "nsg",
                "rule",
                "show",
                "-g",
                resource_group,
                "--nsg-name",
                str(ctx["nsg_name"]),
                "-n",
                str(ctx.get("nsg_rule_name", "fdai-chaos-deny")),
                "--query",
                "access",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    if ref == "az:lb-backend-remove":
        return AzCliStateProbe(
            command=(
                "az",
                "network",
                "lb",
                "address-pool",
                "show",
                "-g",
                resource_group,
                "--lb-name",
                str(ctx["lb_name"]),
                "-n",
                str(ctx["lb_pool_name"]),
                "--query",
                "loadBalancerBackendAddresses[].name",
                "-o",
                "tsv",
            ),
            absent_substrings=(str(ctx["lb_address_name"]),),
        )
    if ref == "az:servicebus-firewall":
        return AzCliStateProbe(
            command=(
                "az",
                "servicebus",
                "namespace",
                "network-rule-set",
                "show",
                "-g",
                resource_group,
                "--namespace-name",
                str(ctx["servicebus_namespace"]),
                "--query",
                "defaultAction",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    raise ValueError(f"{entry.id}: no Azure state probe for {ref!r}")


__all__ = [name for name in globals() if name.startswith(("_build_", "_vm_"))]
