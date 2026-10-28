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
