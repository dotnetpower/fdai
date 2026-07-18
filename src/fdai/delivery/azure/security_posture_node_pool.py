"""AKS node-pool controls for the Azure security posture analyzer."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fdai.core.security import SecurityControlObservation
from fdai.delivery.azure.security_posture_helpers import (
    bool_status,
    control,
    display,
    lookup,
    mapping,
    presence_status,
)
from fdai.shared.providers.inventory import ResourceRecord

_AKS_GUIDANCE: Final[str] = "https://learn.microsoft.com/azure/aks/concepts-security"


def node_pool_controls(
    record: ResourceRecord, *, assessed_at: datetime
) -> tuple[SecurityControlObservation, ...]:
    """Evaluate host-security and patch evidence for one AKS node pool."""

    props = mapping(record.props.get("properties"))
    security = mapping(props.get("securityProfile"))
    return (
        control(
            record,
            assessed_at,
            "aks-node-image",
            "Node image patch level",
            "patching",
            presence_status(lookup(props, "nodeImageVersion")),
            "high",
            display(lookup(props, "nodeImageVersion")),
            "recorded",
            "azure-resource-graph",
            "The node image version is required for bulletin applicability.",
            validation="Compare the image version with the AKS release bulletin.",
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-node-secure-boot",
            "Node secure boot",
            "host-security",
            bool_status(lookup(security, "enableSecureBoot")),
            "medium",
            display(lookup(security, "enableSecureBoot")),
            "true",
            "azure-resource-graph",
            "Secure boot protects the node boot chain where supported.",
            remediation="Enable trusted launch secure boot on supported node pools.",
            validation="Verify secure boot in the node-pool security profile.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
        control(
            record,
            assessed_at,
            "aks-node-vtpm",
            "Node virtual TPM",
            "host-security",
            bool_status(lookup(security, "enableVtpm")),
            "medium",
            display(lookup(security, "enableVtpm")),
            "true",
            "azure-resource-graph",
            "vTPM provides measured boot evidence where supported.",
            remediation="Enable vTPM on supported node pools.",
            validation="Verify vTPM in the node-pool security profile.",
            priority="medium",
            due_days=30,
            source_url=_AKS_GUIDANCE,
        ),
    )


__all__ = ["node_pool_controls"]
