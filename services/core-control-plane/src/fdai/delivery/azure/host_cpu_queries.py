"""Additive VMSS platform CPU template; VM keeps its existing reviewed route."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.core.investigation.host_cpu import METRIC_VMSS_CPU_PERCENT
from fdai.delivery.azure.metrics_api import MetricsApiTemplate


def vmss_cpu_metric_templates() -> Mapping[str, MetricsApiTemplate]:
    """Register alongside metrics_api_queries defaults, never replace MySQL/VM CPU.

    This is the scale-set platform aggregate, not a hottest-member or guest-OS
    diagnosis. Exact VMSS child instances need a separately reviewed provider
    route; a successful parent provisioning state does not establish CPU.
    """

    return MappingProxyType(
        {
            METRIC_VMSS_CPU_PERCENT: MetricsApiTemplate(
                azure_metric_name="Percentage CPU",
                aggregation="Average",
                resource_type="Microsoft.Compute/virtualMachineScaleSets",
            )
        }
    )


def vm_and_vmss_host_metric_templates() -> Mapping[str, MetricsApiTemplate]:
    """Extended Azure Monitor platform host metrics for VM and VMSS resources."""
    vm_type = "Microsoft.Compute/virtualMachines"
    vmss_type = "Microsoft.Compute/virtualMachineScaleSets"
    return MappingProxyType(
        {
            **vmss_cpu_metric_templates(),
            "vm.available_memory_bytes": MetricsApiTemplate(
                azure_metric_name="Available Memory Bytes",
                aggregation="Minimum",
                resource_type=vm_type,
            ),
            "vmss.available_memory_bytes": MetricsApiTemplate(
                azure_metric_name="Available Memory Bytes",
                aggregation="Minimum",
                resource_type=vmss_type,
            ),
            "vm.disk_read_iops": MetricsApiTemplate(
                azure_metric_name="Disk Read Operations/Sec",
                aggregation="Average",
                resource_type=vm_type,
            ),
            "vm.disk_write_iops": MetricsApiTemplate(
                azure_metric_name="Disk Write Operations/Sec",
                aggregation="Average",
                resource_type=vm_type,
            ),
            "vm.network_in_total_bytes": MetricsApiTemplate(
                azure_metric_name="Network In Total",
                aggregation="Total",
                resource_type=vm_type,
            ),
            "vm.network_out_total_bytes": MetricsApiTemplate(
                azure_metric_name="Network Out Total",
                aggregation="Total",
                resource_type=vm_type,
            ),
        }
    )


__all__ = [
    "vm_and_vmss_host_metric_templates",
    "vmss_cpu_metric_templates",
]
