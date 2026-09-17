const applicationGateway = new URL(
  "../../../tools/architecture-diagrams/assets/azure/application-gateway.svg",
  import.meta.url,
).href;
const firewall = new URL(
  "../../../tools/architecture-diagrams/assets/azure/firewall.svg",
  import.meta.url,
).href;
const loadBalancer = new URL(
  "../../../tools/architecture-diagrams/assets/azure/load-balancer.svg",
  import.meta.url,
).href;
const networkInterface = new URL(
  "../../../tools/architecture-diagrams/assets/azure/network-interface.svg",
  import.meta.url,
).href;
const networkSecurityGroup = new URL(
  "../../../tools/architecture-diagrams/assets/azure/network-security-group.svg",
  import.meta.url,
).href;
const privateEndpoint = new URL(
  "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg",
  import.meta.url,
).href;
const publicIp = new URL(
  "../../../tools/architecture-diagrams/assets/azure/public-ip.svg",
  import.meta.url,
).href;
const routeTable = new URL(
  "../../../tools/architecture-diagrams/assets/azure/route-table.svg",
  import.meta.url,
).href;
const subnet = new URL(
  "../../../tools/architecture-diagrams/assets/azure/subnet.svg",
  import.meta.url,
).href;
const virtualMachine = new URL(
  "../../../tools/architecture-diagrams/assets/azure/virtual-machine.svg",
  import.meta.url,
).href;
const virtualNetwork = new URL(
  "../../../tools/architecture-diagrams/assets/azure/virtual-network.svg",
  import.meta.url,
).href;
const virtualNetworkGateway = new URL(
  "../../../tools/architecture-diagrams/assets/azure/virtual-network-gateway.svg",
  import.meta.url,
).href;

const NETWORK_ICON_URL_BY_RESOURCE_TYPE: Readonly<Record<string, string>> = Object.freeze({
  "compute.vm": virtualMachine,
  "microsoft.compute/virtualmachines": virtualMachine,
  "microsoft.network/applicationgateways": applicationGateway,
  "microsoft.network/azurefirewalls": firewall,
  "microsoft.network/loadbalancers": loadBalancer,
  "microsoft.network/networkinterfaces": networkInterface,
  "microsoft.network/networksecuritygroups": networkSecurityGroup,
  "microsoft.network/privateendpoints": privateEndpoint,
  "microsoft.network/publicipaddresses": publicIp,
  "microsoft.network/routetables": routeTable,
  "microsoft.network/virtualnetworkgateways": virtualNetworkGateway,
  "microsoft.network/virtualnetworks": virtualNetwork,
  "microsoft.network/virtualnetworks/subnets": subnet,
  "network.application-gateway": applicationGateway,
  "network.firewall": firewall,
  "network.interface": networkInterface,
  "network.load-balancer": loadBalancer,
  "network.nsg": networkSecurityGroup,
  "network.private-endpoint": privateEndpoint,
  "network.public-ip": publicIp,
  "network.route-table": routeTable,
  "network.subnet": subnet,
  "network.virtual-network-gateway": virtualNetworkGateway,
  "network.vnet": virtualNetwork,
  subnet,
  "virtual-network": virtualNetwork,
});

/** Resolves only reviewed Azure resource types to digest-locked official icon URLs. */
export function architectureNetworkIconUrlForResourceType(type: string): string | undefined {
  return NETWORK_ICON_URL_BY_RESOURCE_TYPE[type.trim().toLowerCase()];
}
