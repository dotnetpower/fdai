import applicationGateway from "../../../tools/architecture-diagrams/assets/azure/application-gateway.svg?url";
import applicationGatewaySource from "../../../tools/architecture-diagrams/assets/azure/application-gateway.svg?raw";
import firewall from "../../../tools/architecture-diagrams/assets/azure/firewall.svg?url";
import firewallSource from "../../../tools/architecture-diagrams/assets/azure/firewall.svg?raw";
import loadBalancer from "../../../tools/architecture-diagrams/assets/azure/load-balancer.svg?url";
import loadBalancerSource from "../../../tools/architecture-diagrams/assets/azure/load-balancer.svg?raw";
import networkInterface from "../../../tools/architecture-diagrams/assets/azure/network-interface.svg?url";
import networkInterfaceSource from "../../../tools/architecture-diagrams/assets/azure/network-interface.svg?raw";
import networkSecurityGroup from "../../../tools/architecture-diagrams/assets/azure/network-security-group.svg?url";
import networkSecurityGroupSource from "../../../tools/architecture-diagrams/assets/azure/network-security-group.svg?raw";
import privateEndpoint from "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg?url";
import privateEndpointSource from "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg?raw";
import publicIp from "../../../tools/architecture-diagrams/assets/azure/public-ip.svg?url";
import publicIpSource from "../../../tools/architecture-diagrams/assets/azure/public-ip.svg?raw";
import routeTable from "../../../tools/architecture-diagrams/assets/azure/route-table.svg?url";
import routeTableSource from "../../../tools/architecture-diagrams/assets/azure/route-table.svg?raw";
import subnet from "../../../tools/architecture-diagrams/assets/azure/subnet.svg?url";
import subnetSource from "../../../tools/architecture-diagrams/assets/azure/subnet.svg?raw";
import virtualMachine from "../../../tools/architecture-diagrams/assets/azure/virtual-machine.svg?url";
import virtualMachineSource from "../../../tools/architecture-diagrams/assets/azure/virtual-machine.svg?raw";
import virtualNetwork from "../../../tools/architecture-diagrams/assets/azure/virtual-network.svg?url";
import virtualNetworkSource from "../../../tools/architecture-diagrams/assets/azure/virtual-network.svg?raw";
import virtualNetworkGateway from "../../../tools/architecture-diagrams/assets/azure/virtual-network-gateway.svg?url";
import virtualNetworkGatewaySource from "../../../tools/architecture-diagrams/assets/azure/virtual-network-gateway.svg?raw";

interface NetworkIconAsset {
  readonly url: string;
  readonly source: string;
}

const asset = (url: string, source: string): NetworkIconAsset => ({ url, source });
const applicationGatewayAsset = asset(applicationGateway, applicationGatewaySource);
const firewallAsset = asset(firewall, firewallSource);
const loadBalancerAsset = asset(loadBalancer, loadBalancerSource);
const networkInterfaceAsset = asset(networkInterface, networkInterfaceSource);
const networkSecurityGroupAsset = asset(networkSecurityGroup, networkSecurityGroupSource);
const privateEndpointAsset = asset(privateEndpoint, privateEndpointSource);
const publicIpAsset = asset(publicIp, publicIpSource);
const routeTableAsset = asset(routeTable, routeTableSource);
const subnetAsset = asset(subnet, subnetSource);
const virtualMachineAsset = asset(virtualMachine, virtualMachineSource);
const virtualNetworkAsset = asset(virtualNetwork, virtualNetworkSource);
const virtualNetworkGatewayAsset = asset(virtualNetworkGateway, virtualNetworkGatewaySource);

const NETWORK_ICON_BY_RESOURCE_TYPE: Readonly<Record<string, NetworkIconAsset>> = Object.freeze({
  "compute.vm": virtualMachineAsset,
  "microsoft.compute/virtualmachines": virtualMachineAsset,
  "microsoft.network/applicationgateways": applicationGatewayAsset,
  "microsoft.network/azurefirewalls": firewallAsset,
  "microsoft.network/loadbalancers": loadBalancerAsset,
  "microsoft.network/networkinterfaces": networkInterfaceAsset,
  "microsoft.network/networksecuritygroups": networkSecurityGroupAsset,
  "microsoft.network/privateendpoints": privateEndpointAsset,
  "microsoft.network/publicipaddresses": publicIpAsset,
  "microsoft.network/routetables": routeTableAsset,
  "microsoft.network/virtualnetworkgateways": virtualNetworkGatewayAsset,
  "microsoft.network/virtualnetworks": virtualNetworkAsset,
  "microsoft.network/virtualnetworks/subnets": subnetAsset,
  "network.application-gateway": applicationGatewayAsset,
  "network.firewall": firewallAsset,
  "network.interface": networkInterfaceAsset,
  "network.load-balancer": loadBalancerAsset,
  "network.nsg": networkSecurityGroupAsset,
  "network.private-endpoint": privateEndpointAsset,
  "network.public-ip": publicIpAsset,
  "network.route-table": routeTableAsset,
  "network.subnet": subnetAsset,
  "network.virtual-network-gateway": virtualNetworkGatewayAsset,
  "network.vnet": virtualNetworkAsset,
  subnet: subnetAsset,
  "virtual-network": virtualNetworkAsset,
});
const iconDataUriByUrl = new Map<string, string>();

/** Resolves only reviewed Azure resource types to digest-locked official icons. */
export function architectureNetworkIconForResourceType(type: string): string | undefined {
  return NETWORK_ICON_BY_RESOURCE_TYPE[type.trim().toLowerCase()]?.url;
}

/** Accepts SVG-only icon content with no script, foreign content, or external references. */
export function architectureNetworkIconSourceIsSafe(source: string): boolean {
  return source.startsWith("<svg ") &&
    !/<(?:script|foreignObject)\b/iu.test(source) &&
    !/\bsrc\s*=/iu.test(source) &&
    !/\bhref\s*=\s*["'](?!#)/iu.test(source);
}

/** Embeds a reviewed icon for a self-contained downloaded artifact. */
export async function architectureNetworkIconDataUriForResourceType(
  type: string,
): Promise<string | undefined> {
  const icon = NETWORK_ICON_BY_RESOURCE_TYPE[type.trim().toLowerCase()];
  if (!icon) return undefined;
  const { source, url } = icon;
  const cached = iconDataUriByUrl.get(url);
  if (cached) return cached;
  if (!architectureNetworkIconSourceIsSafe(source)) {
    throw new Error("Reviewed network icon contains unsupported SVG content");
  }
  const bytes = new TextEncoder().encode(source);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  const dataUri = `data:image/svg+xml;base64,${btoa(binary)}`;
  iconDataUriByUrl.set(url, dataUri);
  return dataUri;
}
