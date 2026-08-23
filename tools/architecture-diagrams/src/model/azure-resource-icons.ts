const AZURE_RESOURCE_ICON_BY_TYPE: Readonly<Record<string, string>> = Object.freeze({
  "microsoft.compute/virtualmachines": "virtual-machine",
  "microsoft.network/applicationgateways": "application-gateway",
  "microsoft.network/azurefirewalls": "firewall",
  "microsoft.network/bastionhosts": "bastion",
  "microsoft.network/expressroutecircuits": "expressroute-circuit",
  "microsoft.network/loadbalancers": "load-balancer",
  "microsoft.network/networkinterfaces": "network-interface",
  "microsoft.network/networksecuritygroups": "network-security-group",
  "microsoft.network/privateendpoints": "private-endpoint",
  "microsoft.network/publicipaddresses": "public-ip",
  "microsoft.network/routetables": "route-table",
  "microsoft.network/virtualhubs": "virtual-hub",
  "microsoft.network/virtualnetworkgateways": "virtual-network-gateway",
  "microsoft.network/virtualnetworks": "virtual-network",
  "microsoft.network/virtualnetworks/subnets": "subnet",
  "microsoft.network/virtualwans": "virtual-wan",
  "network.application-gateway": "application-gateway",
  "network.firewall": "firewall",
  "network.interface": "network-interface",
  "network.load-balancer": "load-balancer",
  "network.nsg": "network-security-group",
  "network.private-endpoint": "private-endpoint",
  "network.public-ip": "public-ip",
  "network.route-table": "route-table",
  "network.subnet": "subnet",
  "network.virtual-network-gateway": "virtual-network-gateway",
  "network.vnet": "virtual-network",
  "compute.vm": "virtual-machine",
});

/** Resolves only reviewed Azure resource types to verified official icon ids. */
export function azureDiagramIconForResourceType(resourceType: string | undefined): string | undefined {
  return resourceType ? AZURE_RESOURCE_ICON_BY_TYPE[resourceType.trim().toLowerCase()] : undefined;
}

/** Returns the complete reviewed resource-type mapping for contract tests. */
export function azureDiagramResourceIconEntries(): ReadonlyArray<readonly [string, string]> {
  return Object.entries(AZURE_RESOURCE_ICON_BY_TYPE);
}
