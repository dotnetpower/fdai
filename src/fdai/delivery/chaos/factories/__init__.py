"""Register delivery-layer builders for catalog-backed chaos scenarios.

Builder implementations live in focused sibling modules. Imports below
preserve the historical ``fdai.delivery.chaos.factories`` symbol surface.
"""

from __future__ import annotations

from fdai.core.chaos.factory import ScenarioFactory
from fdai.delivery.chaos.factory_injectors import (
    _build_aoai_rate_limit,
    _build_az_cosmosdb_failover,
    _build_az_keyvault_deny,
    _build_az_lb_backend_remove,
    _build_az_nsg_rule,
    _build_az_redis_reboot,
    _build_az_servicebus_firewall,
    _build_az_vm_lifecycle,
    _build_az_vm_network_disconnect,
    _build_az_vm_network_latency,
    _build_az_vm_packet_loss,
    _build_az_vm_run_command,
    _build_az_vm_stop_service,
    _build_az_vmss_lifecycle,
    _build_chaos_mesh,
    _build_detection_only,
    _build_kubectl_pod_kill,
    _build_kubectl_scale,
    _build_kubectl_set_image,
    _build_litmus,
    _build_mysql_query_load,
)
from fdai.delivery.chaos.factory_probes import (
    _build_backend_health_probe,
    _build_cm_status_probe,
    _build_db_cpu_probe,
    _build_gpu_sku_mismatch_probe,
    _build_host_cpu_probe,
    _build_host_memory_probe,
    _build_pod_restart_probe,
    _build_rate_limit_probe,
    _build_rollout_stall_probe,
)


def register_default_builders(factory: ScenarioFactory) -> ScenarioFactory:
    """Register every builder the delivery layer ships today."""
    factory.register_injector("chaos-mesh", _build_chaos_mesh)
    factory.register_injector("litmus", _build_litmus)
    factory.register_injector("kubectl:pod-kill", _build_kubectl_pod_kill)
    factory.register_injector("kubectl:scale", _build_kubectl_scale)
    factory.register_injector("kubectl:set-image", _build_kubectl_set_image)
    factory.register_injector("az:vm-run-command", _build_az_vm_run_command)
    factory.register_injector("mysql:query-load", _build_mysql_query_load)
    factory.register_injector("aoai:rate-limit", _build_aoai_rate_limit)
    factory.register_injector("az:vm-network-latency", _build_az_vm_network_latency)
    factory.register_injector("az:vm-packet-loss", _build_az_vm_packet_loss)
    factory.register_injector("az:vm-network-disconnect", _build_az_vm_network_disconnect)
    factory.register_injector("az:vm-stop-service", _build_az_vm_stop_service)
    factory.register_injector("az:vm-lifecycle", _build_az_vm_lifecycle)
    factory.register_injector("az:vmss-lifecycle", _build_az_vmss_lifecycle)
    factory.register_injector("az:redis-reboot", _build_az_redis_reboot)
    factory.register_injector("az:cosmosdb-failover", _build_az_cosmosdb_failover)
    factory.register_injector("az:keyvault-deny", _build_az_keyvault_deny)
    factory.register_injector("az:nsg-rule", _build_az_nsg_rule)
    factory.register_injector("az:lb-backend-remove", _build_az_lb_backend_remove)
    factory.register_injector("az:servicebus-firewall", _build_az_servicebus_firewall)
    factory.register_injector("probe-only", _build_detection_only)

    factory.register_probe("pod_restart", _build_pod_restart_probe)
    factory.register_probe("backend_health", _build_backend_health_probe)
    factory.register_probe("rollout_stall", _build_rollout_stall_probe)
    factory.register_probe("host_cpu", _build_host_cpu_probe)
    factory.register_probe("host_memory", _build_host_memory_probe)
    factory.register_probe("db_cpu", _build_db_cpu_probe)
    factory.register_probe("rate_limit", _build_rate_limit_probe)
    factory.register_probe("gpu_sku_mismatch", _build_gpu_sku_mismatch_probe)
    for cm_signal in (
        "gateway_latency",
        "request_failure",
        "node_cpu",
    ):
        factory.register_probe(cm_signal, _build_cm_status_probe)
    return factory


def default_factory() -> ScenarioFactory:
    """Return a ready-to-use factory with every default builder registered."""
    return register_default_builders(ScenarioFactory())


__all__ = ["default_factory", "register_default_builders"]
