"""Ingest Azure Chaos Studio fault library into the FDAI catalog.

Azure Chaos Studio publishes ~50 faults across VM, VMSS, AKS, Key
Vault, Cosmos DB, Redis, AAD, Service Bus, Load Balancer, Storage,
and more. Chaos Studio itself is a *managed orchestrator* - each
fault is a thin wrapper over one or more Azure Resource Manager
operations FDAI can invoke directly through the `az` CLI. This
ingester therefore projects each fault into the FDAI catalog with
the equivalent `az:*` injector string, NOT `needs-injector`. The
delivery-layer implementations live in
:mod:`fdai.delivery.chaos.azure_ops`.

Reclassification (2026-07-13):

- The 3 AKS "chaos-mesh-*" entries the Chaos Studio catalog exposes
  are one-to-one wrappers over Chaos Mesh CRDs the FDAI catalog
  already ships under `collected/chaos-mesh/` - they were dropped
  from this ingester to avoid duplicate scenarios.
- The 2 agent-based CPU / memory pressure entries reuse the shipped
  :class:`AzVmCpuStressInjector` / :class:`AzVmMemStressInjector` via
  the existing `az:vm-run-command` prefix.
- The 4 remaining agent-based entries (network latency, packet loss,
  disconnect, stop-service) route through new `az:vm-*` builders
  backed by classes in :mod:`fdai.delivery.chaos.azure_ops`.
- The 9 resource-level entries (VM shutdown/redeploy, VMSS shutdown,
  Redis reboot, Cosmos failover, Key Vault deny, NSG rule, LB backend
  remove, Service Bus firewall) each get a dedicated `az:*` injector
  string that maps to a class in `azure_ops.py`.

Output: `rule-catalog/chaos-scenarios/collected/azure-chaos-studio/`.
Idempotent - the runner rewrites the same files every run and prunes
any file whose slug is no longer in `_ENTRIES`.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "azure-chaos-studio"
_ALERT_WINDOW_S = 360.0


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    fault_name: str  # Azure Chaos Studio upstream spelling, preserved verbatim
    injector: str  # FDAI catalog injector string; matches a delivery factory
    description: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    params: dict[str, str]
    rollback_note: str
    blast_radius_cap: int = 1
    tags: tuple[str, ...] = ("azure-chaos-studio",)


# 15 entries after dropping the 3 chaos-mesh CRD wrapper duplicates.
_ENTRIES: tuple[Entry, ...] = (
    # -- Guest-OS agent-based (via az vm run-command) --------------------
    Entry(
        slug="agent-cpu-pressure",
        fault_name="urn:csci:microsoft:agent:cpuPressure/1.0",
        injector="az:vm-run-command",
        description="Sustain CPU pressure on a VM via the Chaos Studio "
        "agent-based fault - percentage of cores loaded for a bounded window. "
        "FDAI wires this through az vm run-command + stress-ng (no Chaos "
        "Studio service needed).",
        category="compute",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={
            "fault_name": "urn:csci:microsoft:agent:cpuPressure/1.0",
            "pressure_level": "95",
        },
        rollback_note="stress-ng is killed on stop; run-command clears the process.",
        tags=("azure-chaos-studio", "vm", "cpu"),
    ),
    Entry(
        slug="agent-physical-memory-pressure",
        fault_name="urn:csci:microsoft:agent:physicalMemoryPressure/1.0",
        injector="az:vm-run-command",
        description="Sustain physical memory pressure on a VM via the Chaos "
        "Studio agent-based fault. FDAI wires this through az vm run-command "
        "+ stress-ng --vm.",
        category="resource_saturation",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={
            "fault_name": "urn:csci:microsoft:agent:physicalMemoryPressure/1.0",
            "pressure_level": "95",
            "vm_bytes": "250M",
        },
        rollback_note="stress-ng is killed on stop.",
        tags=("azure-chaos-studio", "vm", "memory"),
    ),
    Entry(
        slug="agent-network-latency",
        fault_name="urn:csci:microsoft:agent:networkLatency/1.0",
        injector="az:vm-network-latency",
        description="Add outbound network latency on a VM via tc netem "
        "delay applied through az vm run-command.",
        category="network",
        target_type="vm",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkLatency/1.0",
            "latency_ms": "250",
        },
        rollback_note="tc qdisc del removes the netem rule on stop.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-network-packet-loss",
        fault_name="urn:csci:microsoft:agent:networkPacketLoss/1.0",
        injector="az:vm-packet-loss",
        description="Drop a fraction of outbound packets on a VM via tc "
        "netem loss (through az vm run-command).",
        category="network",
        target_type="vm",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkPacketLoss/1.0",
            "loss_percent": "20",
        },
        rollback_note="tc qdisc del removes the netem rule on stop.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-network-disconnect",
        fault_name="urn:csci:microsoft:agent:networkDisconnect/1.0",
        injector="az:vm-network-disconnect",
        description="Block outbound traffic to a set of destinations on a "
        "VM via iptables DROP (applied through az vm run-command).",
        category="network",
        target_type="vm",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkDisconnect/1.0",
            "destination": "10.0.0.0/8",
        },
        rollback_note="iptables -D removes the DROP rule on stop.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-stop-service",
        fault_name="urn:csci:microsoft:agent:stopService/1.0",
        injector="az:vm-stop-service",
        description="Stop a systemd unit on a VM via systemctl through az vm run-command.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={
            "fault_name": "urn:csci:microsoft:agent:stopService/1.0",
            "service": "myservice",
        },
        rollback_note="systemctl start restores the unit on stop.",
        tags=("azure-chaos-studio", "vm", "service"),
    ),
    # -- Resource-level ARM operations (direct az CLI) --------------------
    Entry(
        slug="vm-shutdown",
        fault_name="urn:csci:microsoft:virtualMachine:shutdown/1.0",
        injector="az:vm-lifecycle",
        description="Deallocate a Virtual Machine via az vm deallocate. "
        "az vm start restores it on rollback.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={
            "fault_name": "urn:csci:microsoft:virtualMachine:shutdown/1.0",
            "action": "deallocate",
        },
        rollback_note="az vm start restores the VM; workload reschedules.",
        tags=("azure-chaos-studio", "vm"),
    ),
    Entry(
        slug="vm-redeploy",
        fault_name="urn:csci:microsoft:virtualMachine:redeploy/1.0",
        injector="az:vm-lifecycle",
        description="Redeploy a Virtual Machine to a new host via az vm "
        "redeploy - forces a hardware-level reset. One-way; monitor the VM "
        "back to Ready.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={
            "fault_name": "urn:csci:microsoft:virtualMachine:redeploy/1.0",
            "action": "redeploy",
        },
        rollback_note="Redeploy is one-way; the VM starts on the new host "
        "automatically. Rollback = observe recovery.",
        tags=("azure-chaos-studio", "vm"),
    ),
    Entry(
        slug="vmss-shutdown",
        fault_name="urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0",
        injector="az:vmss-lifecycle",
        description="Deallocate a VMSS via az vmss deallocate. az vmss "
        "start restores instances on rollback.",
        category="compute",
        target_type="vmss",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={
            "fault_name": "urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0",
            "action": "deallocate",
        },
        rollback_note="az vmss start restores the instance count.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "vmss"),
    ),
    Entry(
        slug="cosmos-db-failover",
        fault_name="urn:csci:microsoft:cosmosDB:failover/1.0",
        injector="az:cosmosdb-failover",
        description="Force a Cosmos DB region failover via az cosmosdb "
        "failover-priority-change; the injector reverses to the original "
        "priority on stop.",
        category="dependency",
        target_type="db",
        fault_family="stop",
        intensity="extreme",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:cosmosDB:failover/1.0",
            "failover_priorities": "Region2=0 Region1=1",
            "original_priorities": "Region1=0 Region2=1",
        },
        rollback_note="Reverse failover-priority-change on stop.",
        tags=("azure-chaos-studio", "cosmos"),
    ),
    Entry(
        slug="keyvault-deny-access",
        fault_name="urn:csci:microsoft:keyVault:denyAccess/1.0",
        injector="az:keyvault-deny",
        description="Flip a Key Vault's default network action to Deny via "
        "az keyvault network-rule / az keyvault update; clients see 403 on "
        "secret retrieval until stop restores the original action.",
        category="dependency",
        target_type="secret_store",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:keyVault:denyAccess/1.0",
            "original_default_action": "Allow",
        },
        rollback_note="Restore the original default network action on stop.",
        tags=("azure-chaos-studio", "keyvault"),
    ),
    Entry(
        slug="redis-reboot",
        fault_name="urn:csci:microsoft:cache:reboot/1.0",
        injector="needs-injector",
        description="Legacy Azure Cache for Redis force-reboot reference. "
        "New cache creation is retired and Azure Managed Redis has no "
        "equivalent reboot action, so this stays non-executable.",
        category="dependency",
        target_type="cache",
        fault_family="stop",
        intensity="extreme",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:cache:reboot/1.0",
            "reboot_type": "AllNodes",
        },
        rollback_note="Reboot is one-way; rollback = observe recovery.",
        tags=("azure-chaos-studio", "redis"),
    ),
    Entry(
        slug="nsg-security-rule",
        fault_name="urn:csci:microsoft:networkSecurityGroup:securityRule/1.0",
        injector="az:nsg-rule",
        description="Add an outbound Deny rule to an NSG via az network nsg "
        "rule create; the injector removes the rule on stop.",
        category="network",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={
            "fault_name": "urn:csci:microsoft:networkSecurityGroup:securityRule/1.0",
            "destination": "*",
        },
        rollback_note="Remove the Deny rule on stop.",
        tags=("azure-chaos-studio", "nsg"),
    ),
    Entry(
        slug="load-balancer-backend-remove",
        fault_name="urn:csci:microsoft:loadBalancer:backendRemove/1.0",
        injector="az:lb-backend-remove",
        description="Remove a backend address from a Load Balancer pool via "
        "az network lb address-pool address remove; the injector re-adds "
        "the address on stop (requires address_ip in context).",
        category="traffic",
        target_type="lb",
        fault_family="deny",
        intensity="high",
        expected_signal="backend_health",
        params={
            "fault_name": "urn:csci:microsoft:loadBalancer:backendRemove/1.0",
        },
        rollback_note="Re-add the backend address on stop.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "lb"),
    ),
    Entry(
        slug="service-bus-firewall-block",
        fault_name="urn:csci:microsoft:serviceBus:firewallBlock/1.0",
        injector="az:servicebus-firewall",
        description="Flip a Service Bus namespace default network action to "
        "Deny via az servicebus namespace network-rule-set update. "
        "Publishers / subscribers see connection refused until stop.",
        category="dependency",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:serviceBus:firewallBlock/1.0",
            "original_default_action": "Allow",
        },
        rollback_note="Restore the original default network action on stop.",
        tags=("azure-chaos-studio", "servicebus"),
    ),
)


def _to_body(e: Entry) -> dict:
    return {
        "id": f"chaos.azure-chaos-studio.{e.slug}",
        "version": 1,
        "provenance": {
            "source": "azure-chaos-studio",
            "source_url": "https://learn.microsoft.com/azure/chaos-studio/chaos-studio-fault-library",
            "source_ref": e.fault_name,
            "synthesis_method": "collected",
        },
        "category": e.category,
        "target_type": e.target_type,
        "fault_family": e.fault_family,
        "intensity": e.intensity,
        "duration_seconds": _ALERT_WINDOW_S if e.intensity != "extreme" else _ALERT_WINDOW_S * 2,
        "expected_signal": e.expected_signal,
        "injector": e.injector,
        "blast_radius_cap": e.blast_radius_cap,
        "rollback_note": e.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": e.description,
        "params": dict(e.params),
        "tags": list(e.tags),
    }


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Drop any stale files from a previous ingest (e.g. the 3 chaos-mesh
    # wrapper duplicates removed on 2026-07-13). Otherwise the loader keeps
    # loading them until someone deletes them by hand.
    valid_names = {f"{e.slug}.yaml" for e in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    written = 0
    for e in _ENTRIES:
        path = _OUT_DIR / f"{e.slug}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(_to_body(e), f, sort_keys=False, default_flow_style=False)
        written += 1
    print(f"wrote {written} Azure Chaos Studio scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
