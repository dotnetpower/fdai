"""Fault-injector builders for catalog-backed chaos scenarios."""

from __future__ import annotations

from typing import Any

import yaml

from fdai.core.chaos.injector import DetectionOnlyInjector, FaultInjector
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.delivery.chaos.aoai_ratelimit import AoaiRateLimitInjector
from fdai.delivery.chaos.azure_ops import (
    AzCosmosFailoverInjector,
    AzKeyVaultDenyAccessInjector,
    AzLbBackendRemoveInjector,
    AzNsgRuleInjector,
    AzRedisRebootInjector,
    AzServiceBusFirewallInjector,
    AzVmLifecycleInjector,
    AzVmNetworkDisconnectInjector,
    AzVmNetworkLatencyInjector,
    AzVmPacketLossInjector,
    AzVmssLifecycleInjector,
    AzVmStopServiceInjector,
)
from fdai.delivery.chaos.chaos_mesh import ChaosMeshInjector
from fdai.delivery.chaos.factory_bodies import (
    _CHAOS_MESH_KINDS,
    _crd_name,
    _litmus_engine_name,
)
from fdai.delivery.chaos.litmus import LitmusChaosInjector
from fdai.delivery.chaos.live_injectors import (
    AzVmCpuStressInjector,
    AzVmMemStressInjector,
    KubectlBackendDownInjector,
    KubectlBadDeployInjector,
    KubectlPodKillInjector,
)
from fdai.delivery.chaos.mutation_scope import (
    ScopedInjector,
    azure_resource_ref,
    kubernetes_deployment_ref,
    kubernetes_node_ref,
    kubernetes_pods_ref,
)
from fdai.delivery.chaos.mysql_load import AzMysqlQueryLoadInjector

_VM = "Microsoft.Compute/virtualMachines"


def _azure_scoped(
    injector: FaultInjector,
    ctx: dict[str, Any],
    provider: str,
    name_key: str,
) -> FaultInjector:
    """Declare the ARM resource the context-bound Azure injector mutates."""

    return ScopedInjector(
        injector,
        resources=lambda: (azure_resource_ref(ctx, provider, str(ctx[name_key])),),
    )


def _pods_scoped(injector: FaultInjector, ctx: dict[str, Any]) -> FaultInjector:
    return ScopedInjector(injector, resources=lambda: (kubernetes_pods_ref(ctx),))


def _build_detection_only(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    return DetectionOnlyInjector(fault_type=str(entry.spec["fault_family"]))


def _build_chaos_mesh(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    injector_ref = str(entry.spec["injector"])
    kind = injector_ref.split(":", 1)[1] if ":" in injector_ref else ""
    body_fn = _CHAOS_MESH_KINDS.get(kind)
    if body_fn is None:
        raise ValueError(
            f"{entry.id}: unknown chaos-mesh CRD kind {kind!r}; "
            f"supported: {sorted(_CHAOS_MESH_KINDS)}"
        )
    built_kind, crd_yaml = body_fn(entry, ctx)
    injector = ChaosMeshInjector(
        fault_type=str(entry.spec.get("fault_family", "chaos_mesh")),
        context=str(ctx["kubectl_context"]),
        kind=built_kind,
        name=_crd_name(entry),
        namespace=str(ctx["chaos_namespace"]),
        crd_yaml=crd_yaml,
    )
    return _pods_scoped(injector, ctx)


def _build_litmus(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    experiment_name = str(entry.spec["provenance"]["source_ref"])
    params = {str(key): str(value) for key, value in (entry.spec.get("params") or {}).items()}
    params["TOTAL_CHAOS_DURATION"] = str(
        min(
            int(float(entry.spec["duration_seconds"])),
            int(ctx.get("litmus_max_duration_seconds", 180)),
        )
    )
    if entry.spec["target_type"] == "node":
        params.pop("NODE_LABEL", None)
        params["TARGET_NODE"] = str(ctx["litmus_target_node"])
    if experiment_name == "container-kill":
        params["TARGET_CONTAINER"] = str(ctx["backend_container"])
    engine_name = _litmus_engine_name(entry)
    body = {
        "apiVersion": "litmuschaos.io/v1alpha1",
        "kind": "ChaosEngine",
        "metadata": {"name": engine_name, "namespace": str(ctx["litmus_namespace"])},
        "spec": {
            "appinfo": {
                "appns": str(ctx["workload_namespace"]),
                "applabel": f"app={ctx['workload_label']}",
                "appkind": "deployment",
            },
            "engineState": "active",
            "annotationCheck": "false",
            "chaosServiceAccount": str(ctx["litmus_service_account"]),
            "experiments": [
                {
                    "name": experiment_name,
                    "spec": {
                        "components": {
                            "env": [
                                {"name": key, "value": value}
                                for key, value in sorted(params.items())
                            ]
                        }
                    },
                }
            ],
        },
    }
    injector = LitmusChaosInjector(
        fault_type=str(entry.spec["fault_family"]),
        context=str(ctx["kubectl_context"]),
        engine_name=engine_name,
        namespace=str(ctx["litmus_namespace"]),
        engine_yaml=yaml.safe_dump(body, sort_keys=False),
    )
    if entry.spec["target_type"] == "node":
        node = str(ctx["litmus_target_node"])
        return ScopedInjector(injector, resources=lambda: (kubernetes_node_ref(ctx, node),))
    return _pods_scoped(injector, ctx)


def _build_kubectl_pod_kill(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    injector = KubectlPodKillInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
    )
    selector = f"app={ctx['workload_label']}" if "workload_label" in ctx else None
    return ScopedInjector(
        injector,
        resources=lambda: (kubernetes_pods_ref(ctx),),
        bound_target=selector,
    )


def _build_kubectl_scale(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    deployment = str(ctx.get("backend_deployment", "api-backend"))
    injector = KubectlBackendDownInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        deployment=deployment,
        restore_replicas=int(ctx.get("backend_restore_replicas", 3)),
    )
    return ScopedInjector(
        injector,
        resources=lambda: (kubernetes_deployment_ref(ctx, deployment),),
    )


def _build_kubectl_set_image(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    bad_tag = str(p.get("bad_image_tag", "does-not-exist"))
    base = str(ctx.get("backend_image", "nginx"))
    deployment = str(ctx.get("backend_deployment", "api-backend"))
    injector = KubectlBadDeployInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        deployment=deployment,
        container=str(ctx.get("backend_container", "web")),
        bad_image=f"{base}:{bad_tag}",
    )
    return ScopedInjector(
        injector,
        resources=lambda: (kubernetes_deployment_ref(ctx, deployment),),
    )


def _build_az_vm_run_command(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    signal = entry.expected_signal
    duration = int(entry.spec.get("duration_seconds", 600))
    if signal == "host_cpu":
        cpu = AzVmCpuStressInjector(
            resource_group=str(ctx["resource_group"]),
            vm_name=str(ctx["vm_name"]),
            duration_seconds=duration,
        )
        return _azure_scoped(cpu, ctx, _VM, "vm_name")
    if signal == "host_memory":
        p = entry.spec.get("params") or {}
        memory = AzVmMemStressInjector(
            resource_group=str(ctx["resource_group"]),
            vm_name=str(ctx["vm_name"]),
            vm_bytes=str(p.get("vm_bytes", "250M")),
            duration_seconds=duration,
        )
        return _azure_scoped(memory, ctx, _VM, "vm_name")
    raise ValueError(
        f"{entry.id}: az:vm-run-command builder has no dispatch for expected_signal={signal!r}"
    )


def _build_mysql_query_load(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    params = entry.spec.get("params") or {}
    injector = AzMysqlQueryLoadInjector(
        connect_factory=ctx["mysql_connect_factory"],
        concurrent_queries=int(params.get("concurrent_queries", 4)),
    )
    return ScopedInjector(injector, resources=lambda: (str(ctx["mysql_server_resource_id"]),))


def _build_aoai_rate_limit(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    params = entry.spec.get("params") or {}
    injector = AoaiRateLimitInjector(
        request_fn=ctx["aoai_load_request_fn"],
        concurrency=int(params.get("concurrency", 8)),
    )
    return ScopedInjector(injector, resources=lambda: (str(ctx["aoai_resource_id"]),))


def _build_az_vm_network_latency(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzVmNetworkLatencyInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        latency_ms=int(p.get("latency_ms", 250)),
        interface=str(ctx.get("vm_interface", "eth0")),
    )
    return _azure_scoped(injector, ctx, _VM, "vm_name")


def _build_az_vm_packet_loss(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzVmPacketLossInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        loss_percent=int(p.get("loss_percent", 20)),
        interface=str(ctx.get("vm_interface", "eth0")),
    )
    return _azure_scoped(injector, ctx, _VM, "vm_name")


def _build_az_vm_network_disconnect(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    destination = str(p.get("destination", ctx.get("network_disconnect_destination", "10.0.0.0/8")))
    injector = AzVmNetworkDisconnectInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        destination=destination,
    )
    return _azure_scoped(injector, ctx, _VM, "vm_name")


def _build_az_vm_stop_service(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    service = str(p.get("service", ctx.get("stop_service_name", "myservice")))
    injector = AzVmStopServiceInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        service=service,
    )
    return _azure_scoped(injector, ctx, _VM, "vm_name")


def _build_az_vm_lifecycle(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzVmLifecycleInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        action=str(p.get("action", "deallocate")),
    )
    return _azure_scoped(injector, ctx, _VM, "vm_name")


def _build_az_vmss_lifecycle(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzVmssLifecycleInjector(
        resource_group=str(ctx["resource_group"]),
        vmss_name=str(ctx["vmss_name"]),
        action=str(p.get("action", "deallocate")),
    )
    return _azure_scoped(injector, ctx, "Microsoft.Compute/virtualMachineScaleSets", "vmss_name")


def _build_az_redis_reboot(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzRedisRebootInjector(
        resource_group=str(ctx["resource_group"]),
        cache_name=str(ctx["redis_cache_name"]),
        reboot_type=str(p.get("reboot_type", "AllNodes")),
    )
    return _azure_scoped(injector, ctx, "Microsoft.Cache/redis", "redis_cache_name")


def _build_az_cosmosdb_failover(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzCosmosFailoverInjector(
        resource_group=str(ctx["resource_group"]),
        account_name=str(ctx["cosmos_account_name"]),
        original_priorities=str(p.get("original_priorities", "")),
        failover_priorities=str(p.get("failover_priorities", "")),
    )
    return _azure_scoped(
        injector, ctx, "Microsoft.DocumentDB/databaseAccounts", "cosmos_account_name"
    )


def _build_az_keyvault_deny(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzKeyVaultDenyAccessInjector(
        resource_group=str(ctx["resource_group"]),
        vault_name=str(ctx["keyvault_name"]),
        original_default_action=str(p.get("original_default_action", "Allow")),
    )
    return _azure_scoped(injector, ctx, "Microsoft.KeyVault/vaults", "keyvault_name")


def _build_az_nsg_rule(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzNsgRuleInjector(
        resource_group=str(ctx["resource_group"]),
        nsg_name=str(ctx["nsg_name"]),
        rule_name=str(ctx.get("nsg_rule_name", "fdai-chaos-deny")),
        priority=int(ctx.get("nsg_rule_priority", 100)),
        destination=str(p.get("destination", "*")),
    )
    return _azure_scoped(injector, ctx, "Microsoft.Network/networkSecurityGroups", "nsg_name")


def _build_az_lb_backend_remove(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    injector = AzLbBackendRemoveInjector(
        resource_group=str(ctx["resource_group"]),
        lb_name=str(ctx["lb_name"]),
        pool_name=str(ctx["lb_pool_name"]),
        address_name=str(ctx["lb_address_name"]),
        address_ip=ctx.get("lb_address_ip"),
    )
    return _azure_scoped(injector, ctx, "Microsoft.Network/loadBalancers", "lb_name")


def _build_az_servicebus_firewall(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    injector = AzServiceBusFirewallInjector(
        resource_group=str(ctx["resource_group"]),
        namespace_name=str(ctx["servicebus_namespace"]),
        original_default_action=str(p.get("original_default_action", "Allow")),
    )
    return _azure_scoped(injector, ctx, "Microsoft.ServiceBus/namespaces", "servicebus_namespace")


__all__ = [name for name in globals() if name.startswith("_build_")]
